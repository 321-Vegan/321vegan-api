from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant
from app.models.restaurant_selection import RestaurantSelection
from app.models.user import User
from app.models.restaurant_edit_suggestion import (
    RestaurantEditSuggestion,
    RestaurantEditSuggestionKind,
    RestaurantEditSuggestionStatus,
)
from app.services.notification import notification_service


class RestaurantNotificationService:
    """Notify users of the moderation outcome of the places they created and
    of the edit suggestions they sent, and of the selections sent to them.

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

    def notify_suggestion_reviewed(
        self,
        db: Session,
        suggestion: RestaurantEditSuggestion,
        status: RestaurantEditSuggestionStatus,
        restaurant_name: str,
        moderator_id: int,
        rejection_reason: str | None = None,
    ) -> None:
        """Tell the author of an edit suggestion it was applied or rejected.

        Called before the suggestion is marked reviewed with [status].
        """
        if suggestion.user_id is None or suggestion.user_id == moderator_id:
            return
        name = f"« {restaurant_name} »"
        if status == RestaurantEditSuggestionStatus.REJECTED:
            notification_type = "restaurant_suggestion.rejected"
            title = "Votre proposition n'a pas été retenue"
            body = (
                f"{name} : {rejection_reason}"
                if rejection_reason
                else f"Votre proposition pour {name} n'a pas été appliquée."
            )
        else:
            notification_type = "restaurant_suggestion.approved"
            title = (
                "Votre proposition a été acceptée en partie"
                if status == RestaurantEditSuggestionStatus.PARTIALLY_APPROVED
                else "Votre proposition a été acceptée"
            )
            body = {
                RestaurantEditSuggestionKind.NO_VEGAN_OPTION:
                    f"{name} a été retiré de la carte. Merci !",
                RestaurantEditSuggestionKind.DUPLICATE:
                    f"{name} a été fusionné avec le lieu existant. Merci !",
            }.get(suggestion.kind, f"Vos modifications de {name} sont en ligne. Merci !")
        notification_service.create(
            db,
            user_id=suggestion.user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            payload={
                "suggestion_id": suggestion.id,
                "restaurant_id": suggestion.restaurant_id,
                # The place kept, for the app to open instead of the delisted one
                **({"merged_into": suggestion.duplicate_of_id}
                   if status != RestaurantEditSuggestionStatus.REJECTED
                   and suggestion.kind == RestaurantEditSuggestionKind.DUPLICATE
                   else {}),
            },
            commit=False,
        )

    def notify_selection_received(
        self,
        db: Session,
        selection: RestaurantSelection,
        sender: User,
        recipient_id: int,
    ) -> None:
        """Tell a user that a selection was sent to them (to accept or not)."""
        notification_service.create(
            db,
            user_id=recipient_id,
            notification_type="restaurant_selection.received",
            title="Nouvelle sélection de lieux",
            body=f"{sender.nickname} vous a envoyé « {selection.title} »",
            payload={"selection_id": selection.id},
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
