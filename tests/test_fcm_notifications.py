from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.models import NotificationDelivery
from app.routes.notification import mark_my_notification_read
from app.services.fcm import FCMClient, FCMResult
from app.services.notification_delivery import notification_delivery_service as deliveries
from app.services.push_device import push_device_service as devices
from scripts import fcm_worker
from tests.notification_support import NotificationTestCase


class FCMDeliveryTests(NotificationTestCase):
    def process(self, client):
        return deliveries.process_batch(
            self.db, client=client, batch_size=10,
            max_attempts=5, processing_timeout_seconds=300,
        )

    def claim(self, max_attempts=5):
        return deliveries._claim_next(
            self.db, max_attempts=max_attempts, processing_timeout_seconds=300,
        )

    def deliver(self, claim, client):
        return deliveries._deliver_claim(self.db, client=client, claim=claim, max_attempts=5)

    def expire_claim(self):
        self.db.query(NotificationDelivery).one().last_attempt_at = (
            datetime.now() - timedelta(seconds=301)
        )
        self.db.commit()

    def test_delivery_results_and_retry_limit(self):
        for expected, result in (
            ("sent", FCMResult(True, 200, message_id="projects/test/messages/1")),
            ("retry", FCMResult(False, 503, reason="UNAVAILABLE", retryable=True)),
            ("failed", FCMResult(False, 404, reason="UNREGISTERED", invalid_device=True)),
        ):
            with self.subTest(status=expected):
                device = self.register_device()
                notification = self.make_notification()
                client = Mock()
                client.send.return_value = result
                before = datetime.now()
                self.assertEqual(self.process(client), 1)
                row = self.db.query(NotificationDelivery).filter_by(
                    notification_id=notification.id,
                ).one()
                self.assertEqual(row.status, expected)
                self.assertEqual(row.attempt_count, 1)
                self.assertEqual(client.send.call_args.kwargs["user_id"], self.user.id)
                self.assertEqual(client.send.call_args.kwargs["notification_id"], notification.id)
                if expected == "sent":
                    self.assertIsNotNone(row.sent_at)
                    self.assertEqual(row.provider_message_id, result.message_id)
                elif expected == "retry":
                    self.assertGreater(row.next_attempt_at, before + timedelta(minutes=14))
                    row.attempt_count = 4
                    row.next_attempt_at = before
                    self.db.commit()
                    self.process(client)
                    self.db.refresh(row)
                    self.assertEqual((row.attempt_count, row.status), (5, "failed"))
                    self.assertEqual(self.process(client), 0)
                else:
                    self.db.refresh(device)
                    self.assertFalse(device.enabled)
                    self.assertIsNotNone(device.invalidated_at)

    def test_claim_rechecks_cancellation_owner_expiry_and_deletion(self):
        for change in ("logout", "reassign", "expired", "owner_changed", "acknowledged"):
            with self.subTest(change=change):
                device = self.register_device()
                notification = self.make_notification()
                claim = self.claim()
                if change == "logout":
                    devices.deactivate(self.db, device_id=device.id, user_id=self.user.id)
                elif change == "reassign":
                    self.register_device(user_id=self.other_user.id)
                elif change == "acknowledged":
                    mark_my_notification_read(notification.id, self.db, self.user)
                else:
                    if change == "expired":
                        notification.expires_at = datetime.now() - timedelta(seconds=1)
                    else:
                        device.user_id = self.other_user.id
                    self.db.commit()
                client = Mock()
                self.assertFalse(self.deliver(claim, client))
                client.send.assert_not_called()
                if change == "logout":
                    previous_count = self.db.query(NotificationDelivery).count()
                    self.make_notification()
                    self.assertEqual(self.db.query(NotificationDelivery).count(), previous_count)
                row = self.db.get(NotificationDelivery, claim[0])
                if change == "acknowledged":
                    self.assertIsNone(row)
                else:
                    self.assertEqual(row.status, "failed")

    def test_stale_worker_cannot_send_reclaimed_or_completed_delivery(self):
        self.register_device()
        self.make_notification()
        old_claim = self.claim()
        self.expire_claim()
        new_claim = self.claim()
        client = Mock()
        client.send.return_value = FCMResult(True, 200)
        self.assertFalse(self.deliver(old_claim, client))
        self.assertTrue(self.deliver(new_claim, client))
        self.assertFalse(self.deliver(new_claim, client))
        client.send.assert_called_once()

    def test_crash_recovery_stops_at_attempt_limit(self):
        self.register_device()
        self.make_notification()
        for _ in range(2):
            self.assertIsNotNone(self.claim(max_attempts=2))
            self.expire_claim()
        self.assertIsNone(self.claim(max_attempts=2))
        row = self.db.query(NotificationDelivery).one()
        self.assertEqual((row.attempt_count, row.status), (2, "failed"))
        self.assertEqual(row.last_error, "RetryLimitExceeded")

    def test_failed_send_does_not_strand_other_devices(self):
        self.register_device()
        self.register_device(platform="ios", token="ios-token", installation_id="ios-installation")
        self.make_notification()
        client = Mock()
        client.send.side_effect = [RuntimeError("transport failure"), FCMResult(True, 200)]
        self.assertEqual(self.process(client), 2)
        rows = self.db.query(NotificationDelivery).order_by(NotificationDelivery.id).all()
        self.assertEqual([row.status for row in rows], ["retry", "sent"])
        self.assertEqual(rows[0].last_error, "UnexpectedRuntimeError")
        self.assertEqual(
            {call.kwargs["platform"] for call in client.send.call_args_list},
            {"android", "ios"},
        )

    def test_one_shot_worker_signals_batch_failure(self):
        for failure, expected in ((None, 0), (RuntimeError("database failure"), 1)):
            with self.subTest(failure=failure), \
                    patch.object(fcm_worker.settings, "FCM_ENABLED", True), \
                    patch.object(fcm_worker, "FCMClient"), \
                    patch.object(fcm_worker, "log"), \
                    patch.object(fcm_worker, "process_once", return_value=1, side_effect=failure):
                self.assertEqual(fcm_worker.run(once=True), expected)

    def test_android_and_ios_payload_contract(self):
        client = FCMClient(
            SimpleNamespace(FCM_ANDROID_CHANNEL_ID="test-channel"), firebase_app=object(),
        )
        for platform in ("android", "ios"):
            with self.subTest(platform=platform), patch(
                "app.services.fcm.messaging.send", return_value="projects/test/messages/1",
            ) as send:
                device = self.register_device(platform=platform)
                notification = self.make_notification()
                self.assertEqual(self.process(client), 1)
                send.assert_called_once()
                message = send.call_args.args[0]
                # A registered installation ID must never replace the FCM token.
                self.assertIsNotNone(device.installation_id)
                self.assertEqual(message.token, device.token)
                self.assertIsNone(message.fid)
                self.assertEqual(message.notification.title, "Report handled")
                self.assertEqual(message.data, {
                    "notification_id": str(notification.id), "user_id": str(self.user.id),
                    "type": "error_report.handled", "data": '{"error_report_id":42}',
                })
                if platform == "android":
                    self.assertIsNone(message.apns)
                    self.assertEqual(message.android.priority, "high")
                    self.assertLessEqual(message.android.ttl, timedelta(days=28))
                    self.assertEqual(message.android.notification.channel_id, "test-channel")
                else:
                    self.assertIsNone(message.android)
                    self.assertEqual(message.apns.headers["apns-push-type"], "alert")
                    self.assertEqual(message.apns.headers["apns-priority"], "10")
                    self.assertEqual(message.apns.payload.aps.sound, "default")
