from datetime import datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.db import get_db
from app.models import Notification, NotificationDelivery, User
from app.models.user import UserRole
from app.routes.dependencies import get_current_active_user
from app.routes.notification_broadcast import router
from app.services import notification_broadcast
from app.services.notification_broadcast import (
    BROADCAST_TYPE, notification_broadcast_service,
)
from tests.notification_support import NotificationTestCase


class BroadcastNotificationTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        # owner: two devices; other: pushes turned off; inactive: never
        self.register_device(token="owner-1", installation_id="owner-1")
        self.register_device(token="owner-2", installation_id="owner-2",
                             platform="ios")
        off = self.register_device(user_id=self.other_user.id, token="other",
                                   installation_id="other")
        off.enabled = False
        inactive = User(nickname="inactive", email="inactive@example.com",
                        password="test", is_active=False)
        self.db.add(inactive)
        self.db.flush()
        self.register_device(user_id=inactive.id, token="inactive",
                             installation_id="inactive")
        self.db.commit()

    def send(self):
        return notification_broadcast_service.send(
            self.db, title="Titre", body="Texte", sent_by_id=self.user.id,
        )

    def test_recipients_are_active_accounts_taking_pushes(self):
        self.assertEqual(
            notification_broadcast_service.recipient_ids(self.db),
            [self.user.id],
        )

    def test_send_notifies_each_account_once_on_each_device(self):
        broadcast = self.send()

        self.assertEqual(broadcast.recipient_count, 1)
        notifications = self.db.query(Notification).all()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].user_id, self.user.id)
        self.assertEqual(notifications[0].type, BROADCAST_TYPE)
        self.assertEqual(notifications[0].broadcast_id, broadcast.id)
        self.assertEqual(self.db.query(NotificationDelivery).count(), 2)

    def test_send_in_batches(self):
        for index in range(3):
            user = User(nickname=f"user{index}", email=f"user{index}@example.com",
                        password="test", is_active=True)
            self.db.add(user)
            self.db.flush()
            self.register_device(user_id=user.id, token=f"user{index}",
                                 installation_id=f"user{index}")

        with patch.object(notification_broadcast, "BATCH_SIZE", 2):
            broadcast = self.send()

        self.assertEqual(broadcast.recipient_count, 4)
        self.assertEqual(self.db.query(Notification).count(), 4)
        self.assertEqual(self.db.query(NotificationDelivery).count(), 5)

    def test_history_counts_reads_and_pushes(self):
        broadcast = self.send()
        notification = self.db.query(Notification).one()
        notification.read_at = datetime.now()
        first, second = self.db.query(NotificationDelivery).all()
        first.status = "sent"
        second.status = "failed"
        self.db.commit()

        [entry] = notification_broadcast_service.list_with_stats(self.db)

        self.assertEqual(entry["id"], broadcast.id)
        self.assertEqual(entry["sent_by"], "owner")
        self.assertEqual(entry["recipient_count"], 1)
        self.assertEqual(entry["read_count"], 1)
        self.assertEqual(entry["pushes_sent"], 1)
        self.assertEqual(entry["pushes_failed"], 1)
        self.assertEqual(entry["pushes_pending"], 0)


class BroadcastRouteTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.register_device()
        self.app = FastAPI()
        self.app.include_router(router, prefix="/notification-broadcasts")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

    def as_user(self, role):
        self.user.role = role
        self.db.commit()
        self.app.dependency_overrides[get_current_active_user] = lambda: self.user

    def test_admins_only(self):
        self.as_user(UserRole.CONTRIBUTOR)

        self.assertEqual(
            self.client.get("/notification-broadcasts/recipients").status_code, 403,
        )
        response = self.client.post(
            "/notification-broadcasts/", json={"title": "Titre", "body": "Texte"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.query(Notification).count(), 0)

    def test_send_then_listed(self):
        self.as_user(UserRole.ADMIN)

        recipients = self.client.get("/notification-broadcasts/recipients")
        self.assertEqual(recipients.json(), {"count": 1})
        response = self.client.post(
            "/notification-broadcasts/", json={"title": " Titre ", "body": "Texte"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["title"], "Titre")
        self.assertEqual(response.json()["recipient_count"], 1)

        [entry] = self.client.get("/notification-broadcasts/").json()
        self.assertEqual(entry["sent_by"], "owner")
        self.assertEqual(entry["pushes_pending"], 1)

    def test_empty_title_refused(self):
        self.as_user(UserRole.ADMIN)

        response = self.client.post(
            "/notification-broadcasts/", json={"title": "", "body": "Texte"},
        )
        self.assertEqual(response.status_code, 422)
