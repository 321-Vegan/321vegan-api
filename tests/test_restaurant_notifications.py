from types import SimpleNamespace

from app.models import Notification
from app.models.restaurant_edit_suggestion import (
    RestaurantEditSuggestionKind as Kind,
    RestaurantEditSuggestionStatus as Status,
)
from app.services.restaurant_notification import restaurant_notification_service as service
from tests.notification_support import NotificationTestCase


class RestaurantNotificationTests(NotificationTestCase):
    # The Restaurant table uses PostgreSQL-only types: a stand-in is enough
    def restaurant(self, created_by):
        return SimpleNamespace(id=7, name="Chez Tofu", created_by=created_by)

    def test_validated_notifies_creator_with_new_name(self):
        service.notify_validated(
            self.db, self.restaurant(self.user.id), name="Chez Tofu Paris",
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
                    self.db, self.restaurant(self.user.id), reason=reason,
                )
                self.db.commit()
                notification = self.db.query(Notification).order_by(Notification.id.desc()).first()
                self.assertEqual(notification.type, "restaurant.rejected")
                self.assertEqual(notification.body, expected)

    def test_contacted_notifies_creator(self):
        service.notify_contacted(self.db, self.restaurant(self.user.id))
        self.db.commit()
        notification = self.db.query(Notification).one()
        self.assertEqual(notification.user_id, self.user.id)
        self.assertEqual(notification.type, "restaurant.contacted")
        self.assertIn("« Chez Tofu »", notification.body)
        self.assertEqual(notification.payload, {"restaurant_id": 7})

    def test_no_notification_without_creator(self):
        service.notify_validated(self.db, self.restaurant(None))
        service.notify_contacted(self.db, self.restaurant(None))
        service.notify_rejected(self.db, self.restaurant(None), reason=None)
        self.db.commit()
        self.assertEqual(self.db.query(Notification).count(), 0)

    def suggestion(self, kind=Kind.EDIT, user_id=None):
        return SimpleNamespace(id=3, restaurant_id=7, kind=kind, duplicate_of_id=9,
                               user_id=user_id or self.user.id)

    def last_notification(self):
        self.db.commit()
        return self.db.query(Notification).order_by(Notification.id.desc()).first()

    def test_suggestion_applied_message_by_kind_and_status(self):
        for kind, status, title, body in (
            (Kind.EDIT, Status.APPROVED, "Votre proposition a été acceptée",
             "Vos modifications de « Chez Tofu » sont en ligne. Merci !"),
            (Kind.EDIT, Status.PARTIALLY_APPROVED, "Votre proposition a été acceptée en partie",
             "Vos modifications de « Chez Tofu » sont en ligne. Merci !"),
            (Kind.NO_VEGAN_OPTION, Status.APPROVED, "Votre proposition a été acceptée",
             "« Chez Tofu » a été retiré de la carte. Merci !"),
            (Kind.DUPLICATE, Status.APPROVED, "Votre proposition a été acceptée",
             "« Chez Tofu » a été fusionné avec le lieu existant. Merci !"),
        ):
            with self.subTest(kind=kind, status=status):
                service.notify_suggestion_reviewed(
                    self.db, self.suggestion(kind), status,
                    restaurant_name="Chez Tofu", moderator_id=self.other_user.id)
                notification = self.last_notification()
                self.assertEqual(notification.user_id, self.user.id)
                self.assertEqual(notification.type, "restaurant_suggestion.approved")
                self.assertEqual((notification.title, notification.body), (title, body))
                merged = {"merged_into": 9} if kind == Kind.DUPLICATE else {}
                self.assertEqual(notification.payload,
                                 {"suggestion_id": 3, "restaurant_id": 7, **merged})

    def test_suggestion_rejected_with_or_without_reason(self):
        for reason, body in (
            ("Horaires déjà à jour", "« Chez Tofu » : Horaires déjà à jour"),
            (None, "Votre proposition pour « Chez Tofu » n'a pas été appliquée."),
        ):
            with self.subTest(reason=reason):
                service.notify_suggestion_reviewed(
                    self.db, self.suggestion(), Status.REJECTED,
                    restaurant_name="Chez Tofu", moderator_id=self.other_user.id,
                    rejection_reason=reason)
                notification = self.last_notification()
                self.assertEqual(notification.type, "restaurant_suggestion.rejected")
                self.assertEqual(notification.body, body)
                self.assertEqual(notification.payload, {"suggestion_id": 3, "restaurant_id": 7})

    def test_no_suggestion_notification_for_deleted_author_or_own_suggestion(self):
        for suggestion in (self.suggestion(user_id=0), self.suggestion()):
            if suggestion.user_id == 0:
                suggestion.user_id = None
            service.notify_suggestion_reviewed(
                self.db, suggestion, Status.APPROVED,
                restaurant_name="Chez Tofu", moderator_id=self.user.id)
        self.db.commit()
        self.assertEqual(self.db.query(Notification).count(), 0)

    def test_selection_received_notifies_recipient(self):
        service.notify_selection_received(
            self.db, SimpleNamespace(id=5, title="Brunchs à Lyon"),
            sender=self.other_user, recipient_id=self.user.id)
        notification = self.last_notification()
        self.assertEqual(notification.user_id, self.user.id)
        self.assertEqual(notification.type, "restaurant_selection.received")
        self.assertEqual(notification.body, "other vous a envoyé « Brunchs à Lyon »")
        self.assertEqual(notification.payload, {"selection_id": 5})

    def test_notification_is_left_to_the_caller_transaction(self):
        service.notify_validated(self.db, self.restaurant(self.user.id))
        self.db.rollback()
        self.assertEqual(self.db.query(Notification).count(), 0)
