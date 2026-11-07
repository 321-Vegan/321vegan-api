"""Real PostgreSQL locks/transactions; all tables live in a disposable schema.

Run with RUN_POSTGRES_NOTIFICATION_TESTS=1. FCM is always mocked.
"""
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from queue import Queue
from threading import Barrier, Event, local
from unittest.mock import Mock, patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.crud.notification import notification_crud
from app.database.base_class import Base
from app.database.session import SQLALCHEMY_DATABASE_URL
from app.models import ErrorReport, Notification, NotificationDelivery, PushDevice, User
from app.schemas.error_report import ErrorReportUpdate
from app.services.error_report import error_report_service
from app.services.fcm import FCMResult
from app.services.notification import notification_service
from app.services.notification_delivery import notification_delivery_service as deliveries
from app.services.push_device import push_device_service as devices
from tests.notification_support import PRODUCT_TABLES


@unittest.skipUnless(
    os.getenv("RUN_POSTGRES_NOTIFICATION_TESTS") == "1",
    "Set RUN_POSTGRES_NOTIFICATION_TESTS=1 to test real PostgreSQL concurrency",
)
class NotificationConcurrencyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.getenv("NOTIFICATION_TEST_DATABASE_URL", SQLALCHEMY_DATABASE_URL)
        cls.schema = "notification_test_" + uuid4().hex
        cls.admin_engine = create_engine(url)
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.begin() as connection:
            connection.execute(CreateSchema(cls.schema))
        cls.addClassCleanup(cls._drop_schema)
        # No public schema fallback: a missing test table must never resolve to
        # application data. These timeouts also prevent a broken test hanging.
        cls.engine = create_engine(url, connect_args={
            "options": f"-csearch_path={cls.schema} -clock_timeout=5000 -cstatement_timeout=10000",
        })
        cls.addClassCleanup(cls.engine.dispose)
        cls.Session = sessionmaker(bind=cls.engine, autoflush=False)
        Base.metadata.create_all(cls.engine, tables=[
            User.__table__, *PRODUCT_TABLES, ErrorReport.__table__, Notification.__table__,
            PushDevice.__table__,
            NotificationDelivery.__table__,
        ])

    @classmethod
    def _drop_schema(cls):
        with cls.admin_engine.begin() as connection:
            connection.execute(DropSchema(cls.schema, cascade=True))

    def setUp(self):
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.assertEqual(self.db.execute(text("SELECT current_schema()")).scalar(), self.schema)
        for model in (NotificationDelivery, PushDevice, Notification, ErrorReport, User):
            self.db.query(model).delete()
        users = [User(nickname=name, email=f"{name}@example.com", password="test", is_active=True)
                 for name in ("owner", "other")]
        self.db.add_all(users)
        self.db.commit()
        self.owner_id, self.other_id = [user.id for user in users]

    def _register(self, db, user_id=None, token="test-token"):
        return devices.register(
            db, user_id=user_id or self.owner_id, platform="ios",
            token=token, installation_id="test-installation",
        ).id

    def _notify(self, db, commit=True):
        return notification_service.create(
            db, user_id=self.owner_id, notification_type="test", title="Test",
            body="Test", payload={}, commit=commit,
        ).id

    def _in_session(self, operation, started=None):
        with self.Session() as db:
            if started is not None:
                started.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return operation(db)

    def _wait_for_lock(self, pid):
        deadline = time.monotonic() + 3
        with self.admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            while time.monotonic() < deadline:
                wait_type = connection.execute(text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ), {"pid": pid}).scalar()
                if wait_type == "Lock":
                    return
                time.sleep(0.01)
        self.fail("Expected PostgreSQL to block the competing transaction on a lock")

    def test_cursor_order_matches_commit_order_for_one_recipient(self):
        self._register(self.db)
        first_id = self._notify(self.db, commit=False)
        started = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._in_session, self._notify, started)
            try:
                self._wait_for_lock(started.get(timeout=3))
                visible = self._in_session(lambda db: notification_crud.get_since(
                    db, self.owner_id, 0, 100,
                ))
                self.assertEqual(visible, [])
            finally:
                self.db.commit()
            second_id = future.result(timeout=3)
        self.assertGreater(second_id, first_id)
        self.assertEqual([row.id for row in notification_crud.get_since(
            self.db, self.owner_id, first_id, 100,
        )], [second_id])

    def test_concurrent_handling_creates_one_notification_for_the_transition(self):
        self._register(self.db)
        report = ErrorReport(ean="123", comment="Test", created_by=self.owner_id)
        self.db.add(report)
        self.db.commit()
        report_id = report.id
        self.db.query(ErrorReport).filter_by(id=report_id).with_for_update().one()

        def handle_report(db):
            # Even an already-loaded stale object must reflect the locked row.
            stale_report = db.get(ErrorReport, report_id)
            self.assertFalse(stale_report.handled)
            error_report_service.update(db, report_id, ErrorReportUpdate(handled=True))

        started = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._in_session, handle_report, started)
            try:
                self._wait_for_lock(started.get(timeout=3))
                error_report_service.update(self.db, report_id, ErrorReportUpdate(handled=True))
            finally:
                self.db.rollback()
            future.result(timeout=3)
        self.assertTrue(self.db.get(ErrorReport, report_id).handled)
        self.assertEqual(self.db.query(Notification).count(), 1)
        self.assertEqual(self.db.query(NotificationDelivery).count(), 1)

    def test_concurrent_registration_recovers_from_real_unique_conflict(self):
        original = devices._register_without_commit
        barrier = Barrier(2)
        thread_state = local()

        def pause_before_first_commit(db, **kwargs):
            device = original(db, **kwargs)
            if not getattr(thread_state, "paused", False):
                thread_state.paused = True
                barrier.wait(timeout=3)
            return device

        with patch.object(devices, "_register_without_commit", side_effect=pause_before_first_commit) as register:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self._in_session, self._register) for _ in range(2)]
                ids = [future.result(timeout=5) for future in futures]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(register.call_count, 3)  # two inserts, one actual retry
        self.assertEqual(self._register(self.db, token="refreshed-token"), ids[0])
        self.assertEqual(self.db.query(PushDevice).count(), 1)
        self.assertEqual(self.db.query(PushDevice).one().token, "refreshed-token")

    def test_active_send_excludes_other_workers_and_serializes_changes(self):
        for action in ("logout", "reassign", "acknowledge"):
            with self.subTest(action=action):
                device_id = self._register(self.db)
                notification_id = self._notify(self.db)
                claim = deliveries._claim_next(
                    self.db, max_attempts=5, processing_timeout_seconds=300,
                )
                row = self.db.get(NotificationDelivery, claim[0])
                row.last_attempt_at = datetime.now() - timedelta(seconds=301)
                self.db.commit()
                sending, release = Event(), Event()
                client = Mock()

                def send(**kwargs):
                    self.assertEqual(kwargs["notification_id"], notification_id)
                    sending.set()
                    if not release.wait(timeout=5):
                        raise TimeoutError("Test did not release fake send")
                    return FCMResult(True, 200)

                client.send.side_effect = send
                with ThreadPoolExecutor(max_workers=2) as pool:
                    send_future = pool.submit(self._in_session, lambda db: deliveries._deliver_claim(
                        db, client=client, claim=claim, max_attempts=5,
                    ))
                    try:
                        self.assertTrue(sending.wait(timeout=3))
                        other_client = Mock()
                        self.assertEqual(self._in_session(lambda db: deliveries.process_batch(
                            db, client=other_client, batch_size=10,
                            max_attempts=5, processing_timeout_seconds=300,
                        )), 0)
                        other_client.send.assert_not_called()
                        started = Queue()
                        def change_device(db):
                            if action == "logout":
                                return devices.deactivate(db, device_id=device_id, user_id=self.owner_id)
                            if action == "acknowledge":
                                return notification_crud.delete_for_user(db, notification_id, self.owner_id)
                            return self._register(db, self.other_id)
                        change_future = pool.submit(self._in_session, change_device, started)
                        self._wait_for_lock(started.get(timeout=3))
                    finally:
                        release.set()
                    self.assertTrue(send_future.result(timeout=3))
                    change_future.result(timeout=3)
                self.db.expire_all()
                row = self.db.get(NotificationDelivery, claim[0])
                if action == "acknowledge":
                    self.assertIsNone(row)
                    self.assertIsNone(self.db.get(Notification, notification_id))
                else:
                    self.assertEqual(row.status, "sent")
                device = self.db.get(PushDevice, device_id)
                self.assertEqual(device.enabled, action != "logout")
                self.assertEqual(device.user_id, self.other_id if action == "reassign" else self.owner_id)
                client.send.assert_called_once()
