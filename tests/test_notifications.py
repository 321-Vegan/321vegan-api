from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.crud.notification import notification_crud
from app.database.db import get_db
from app.models import ErrorReport, Notification, NotificationDelivery
from app.routes.dependencies import get_current_active_user
from app.routes.error_report import create_error_report
from app.routes.notification import mark_my_notification_read, router
from app.schemas.error_report import ErrorReportCreate, ErrorReportUpdate
from app.services.error_report import error_report_service
from app.services.notification_delivery import notification_delivery_service
from tests.notification_support import NotificationTestCase


class NotificationInboxTests(NotificationTestCase):
    def test_report_notifies_each_handling_transition_not_repeated_requests(self):
        report = create_error_report(
            ErrorReportCreate.model_validate({
                "ean": "123", "comment": "Incorrect label",
                "created_by": self.other_user.id, "handled": True,
            }),
            db=self.db, principal=self.user,
        )
        self.assertEqual(report.created_by, self.user.id)
        self.assertFalse(report.handled)
        for _ in range(2):
            error_report_service.update(self.db, report.id, ErrorReportUpdate(handled=True))
        notification = self.db.query(Notification).one()
        self.assertEqual(notification.user_id, self.user.id)
        self.assertEqual(notification.type, "error_report.handled")
        self.assertEqual(notification.payload, {"error_report_id": report.id})
        first_id = notification.id
        for handled in (False, True, True):
            error_report_service.update(self.db, report.id, ErrorReportUpdate(handled=handled))
        notifications = self.db.query(Notification).all()
        self.assertEqual(len(notifications), 2)  # the previous occurrence is still unread
        self.assertIn(first_id, [row.id for row in notifications])
        for row in notifications:
            mark_my_notification_read(row.id, self.db, self.user)
            self.db.expunge(row)  # end the deleted object's lifecycle; SQLite can reuse IDs
        error_report_service.update(self.db, report.id, ErrorReportUpdate(handled=True))
        self.assertEqual(self.db.query(Notification).count(), 0)
        for handled in (False, True, True):
            error_report_service.update(self.db, report.id, ErrorReportUpdate(handled=handled))
        self.assertEqual(self.db.query(Notification).count(), 1)  # previous occurrences deleted

    def test_unowned_report_does_not_notify(self):
        report = ErrorReport(ean="123", comment="Anonymous report")
        self.db.add(report)
        self.db.commit()
        error_report_service.update(self.db, report.id, ErrorReportUpdate(handled=True))
        self.assertEqual(self.db.query(Notification).count(), 0)

    def test_queue_failure_rolls_back_report_and_notification(self):
        report = ErrorReport(ean="123", comment="Test", created_by=self.user.id)
        self.db.add(report)
        self.db.commit()
        with patch.object(notification_delivery_service, "enqueue_for_notification",
                          side_effect=RuntimeError("queue failed after notification flush")):
            with self.assertRaises(RuntimeError):
                error_report_service.update(self.db, report.id, ErrorReportUpdate(handled=True))
        self.db.refresh(report)
        self.assertFalse(report.handled)
        self.assertEqual(self.db.query(Notification).count(), 0)

    def test_acknowledgement_is_authenticated_scoped_idempotent_and_cascades(self):
        self.register_device()
        notification_id = self.make_notification().id
        app = FastAPI()
        app.include_router(router, prefix="/me/notifications")
        app.dependency_overrides[get_db] = lambda: self.db
        path = f"/me/notifications/{notification_id}/read"
        with TestClient(app) as client:
            self.assertEqual(client.patch(path).status_code, 401)
            app.dependency_overrides[get_current_active_user] = lambda: self.other_user
            response = client.patch(path)
            self.assertEqual((response.status_code, response.content), (204, b""))
            self.assertEqual(self.db.query(Notification).count(), 1)
            self.assertEqual(self.db.query(NotificationDelivery).count(), 1)
            app.dependency_overrides[get_current_active_user] = lambda: self.user
            self.assertIsNone(client.get("/me/notifications/").json()[0]["read_at"])
            for target in (path, path, f"/me/notifications/{notification_id + 1000}/read"):
                response = client.patch(target)
                self.assertEqual((response.status_code, response.content), (204, b""))
            self.assertEqual(client.get("/me/notifications/").json(), [])
        self.assertEqual(self.db.query(Notification).count(), 0)
        self.assertEqual(self.db.query(NotificationDelivery).count(), 0)

    def test_inbox_is_user_scoped_paginated_and_expires(self):
        first = self.make_notification()
        second = self.make_notification()
        self.make_notification(user_id=self.other_user.id)
        device = self.register_device()
        expired = self.make_notification()
        expired_id = expired.id
        expired.expires_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        self.assertEqual(
            [row.id for row in notification_crud.get_since(self.db, self.user.id, first.id, 100)],
            [second.id],
        )
        self.assertEqual(
            [row.id for row in notification_crud.get_since(self.db, self.user.id, 0, 1)],
            [first.id],
        )
        self.assertEqual(notification_crud.delete_expired(self.db), 1)
        self.db.commit()
        self.db.expire_all()
        self.assertIsNone(self.db.get(Notification, expired_id))
        self.assertIsNotNone(self.db.get(Notification, second.id))
        self.assertEqual(device.deliveries, [])  # delivery rows are removed by cascade
