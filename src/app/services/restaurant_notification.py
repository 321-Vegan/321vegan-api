from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant
from app.services.notification import notification_service


class RestaurantNotificationService:
    """Notify a restaurant's creator of its moderation outcome.

    Called by the moderation routes before they commit, so the notification
    is saved in the same transaction as the validation or refusal.
    """

    def notify_validated(
        self,
        db: Session,
        restaurant: Restaurant,
        moderator_id: int,
        name: str | None = None,
    ) -> None:
        """[name]: the new name when the moderator renames it while validating."""
        if not self._has_other_creator(restaurant, moderator_id):
            return
        notification_service.create(
            db,
            user_id=restaurant.created_by,
            notification_type="restaurant.validated",
            title="Votre lieu a été validé",
            body=f"« {name or restaurant.name} » est maintenant visible sur la carte. "
                 "Merci pour votre contribution !",
            payload={"restaurant_id": restaurant.id},
            commit=False,
        )

    def notify_rejected(
        self,
        db: Session,
        restaurant: Restaurant,
        moderator_id: int,
        reason: str | None,
    ) -> None:
        if not self._has_other_creator(restaurant, moderator_id):
            return
        body = (
            f"« {restaurant.name} » : {reason}"
            if reason
            else f"« {restaurant.name} » n'a pas été validé par l'équipe."
        )
        notification_service.create(
            db,
            user_id=restaurant.created_by,
            notification_type="restaurant.rejected",
            title="Votre lieu n'a pas été retenu",
            body=body,
            payload={"restaurant_id": restaurant.id},
            commit=False,
        )

    @staticmethod
    def _has_other_creator(restaurant: Restaurant, moderator_id: int) -> bool:
        # Imported places have no creator; a moderator needs no notification
        # about their own place.
        return (
            restaurant.created_by is not None
            and restaurant.created_by != moderator_id
        )


restaurant_notification_service = RestaurantNotificationService()
