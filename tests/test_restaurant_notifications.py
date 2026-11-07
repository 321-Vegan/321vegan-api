from types import SimpleNamespace

from app.models import Notification
from app.services.restaurant_notification import restaurant_notification_service as service
from tests.notification_support import NotificationTestCase


class RestaurantNotificationTests(NotificationTestCase):
    # The Restaurant table uses PostgreSQL-only types: a stand-in is enough
    def restaurant(self, created_by):
        return SimpleNamespace(id=7, name="Chez Tofu", created_by=created_by)

    def test_validated_notifies_creator_with_new_name(self):
        service.notify_validated(
            self.db, self.restaurant(self.user.id),
            moderator_id=self.other_user.id, name="Chez Tofu Paris",
        )
        self.db.commit()
        notification = self.db.query(Notification).one()
        self.assertEqual(notification.user_id, self.user.id)
        self.assertEqual(notification.type, "restaurant.validated")
        self.assertIn("« Chez Tofu Paris »", notification.body)
        self.assertEqual(notification.payload, {"restaurant_id": 7})

    def test_rejected_notifies_creator_with_or_without_reason(self):
        for reason, expected in (
            ("Déjà sur la carte", "« Chez Tofu » : Déjà sur la carte"),
            (None, "« Chez Tofu » n'a pas été validé par l'équipe."),
        ):
            with self.subTest(reason=reason):
                service.notify_rejected(
                    self.db, self.restaurant(self.user.id),
                    moderator_id=self.other_user.id, reason=reason,
                )
                self.db.commit()
                notification = self.db.query(Notification).order_by(Notification.id.desc()).first()
                self.assertEqual(notification.type, "restaurant.rejected")
                self.assertEqual(notification.body, expected)

    def test_no_notification_without_creator_or_for_own_place(self):
        for created_by in (None, self.user.id):
            service.notify_validated(
                self.db, self.restaurant(created_by), moderator_id=self.user.id)
            service.notify_rejected(
                self.db, self.restaurant(created_by), moderator_id=self.user.id, reason=None)
        self.db.commit()
        self.assertEqual(self.db.query(Notification).count(), 0)

    def test_notification_is_left_to_the_caller_transaction(self):
        service.notify_validated(
            self.db, self.restaurant(self.user.id), moderator_id=self.other_user.id)
        self.db.rollback()
        self.assertEqual(self.db.query(Notification).count(), 0)
