"""Small shared fixture for notification tests; no application DB or real FCM."""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base_class import Base
from app.models import ErrorReport, Notification, NotificationDelivery, PushDevice, User
from app.services.notification import notification_service
from app.services.push_device import push_device_service


class NotificationTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            Base.metadata.create_all(connection, tables=[
                User.__table__, ErrorReport.__table__, Notification.__table__,
                PushDevice.__table__, NotificationDelivery.__table__,
            ])
        self.db = Session(engine, autoflush=False)
        self.addCleanup(self.db.close)
        self.user, self.other_user = [
            User(nickname=name, email=f"{name}@example.com", password="test", is_active=True)
            for name in ("owner", "other")
        ]
        self.db.add_all([self.user, self.other_user])
        self.db.commit()

    def make_notification(self, user_id=None):
        return notification_service.create(
            self.db, user_id=user_id or self.user.id,
            notification_type="error_report.handled", title="Report handled",
            body="A response is available.", payload={"error_report_id": 42},
        )

    def register_device(self, user_id=None, platform="android", token="test-token",
                        installation_id="test-installation"):
        return push_device_service.register(
            self.db, user_id=user_id or self.user.id, platform=platform,
            token=token, installation_id=installation_id,
        )
