from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from app.crud.base import CRUDRepository
from app.models.restaurant import Restaurant
from app.models.restaurant_edit_suggestion import RestaurantEditSuggestion, RestaurantEditSuggestionStatus
from app.models.restaurant_review import RestaurantReview


class RestaurantEditSuggestionCRUDRepository(CRUDRepository):
    def replace_pending(self, db: Session, suggestion: RestaurantEditSuggestion) -> RestaurantEditSuggestion:
        """
        Save a suggestion, replacing the pending one of the same user for the
        same restaurant (one pending suggestion per user and restaurant).

        Parameters:
            db (Session): The database session.
            suggestion (RestaurantEditSuggestion): The new suggestion.

        Returns:
            RestaurantEditSuggestion: The saved suggestion.
        """
        db.query(self._model).filter(
            self._model.restaurant_id == suggestion.restaurant_id,
            self._model.user_id == suggestion.user_id,
            self._model.status == RestaurantEditSuggestionStatus.PENDING,
        ).delete()
        db.flush()
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)
        return suggestion

    def mark_reviewed(
        self,
        db: Session,
        suggestion: RestaurantEditSuggestion,
        status: RestaurantEditSuggestionStatus,
        reviewer_id: int,
        applied_changes: dict = None,
        rejection_reason: str = None,
    ) -> RestaurantEditSuggestion:
        """
        Close a suggestion as applied (in full or in part) or rejected.

        Parameters:
            db (Session): The database session.
            suggestion (RestaurantEditSuggestion): The suggestion.
            status (RestaurantEditSuggestionStatus): The final status.
            reviewer_id (int): The moderator.
            applied_changes (dict): What was really applied, if anything.
            rejection_reason (str): Why it was rejected, if it was.

        Returns:
            RestaurantEditSuggestion: The updated suggestion.
        """
        suggestion.status = status
        suggestion.reviewed_by = reviewer_id
        suggestion.reviewed_at = datetime.now()
        suggestion.applied_changes = applied_changes
        suggestion.rejection_reason = rejection_reason
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)
        return suggestion

    def merge_into(self, db: Session, source: Restaurant, target: Restaurant) -> List[str]:
        """
        Move the reviews and photos of a duplicate restaurant to the one it
        duplicates, without committing. A user who reviewed both keeps the
        review of the target.

        Parameters:
            db (Session): The database session.
            source (Restaurant): The duplicate, to be deleted afterwards.
            target (Restaurant): The restaurant kept.

        Returns:
            List[str]: S3 paths of the photos of the dropped reviews, to
                delete once committed.
        """
        target_reviewers = {
            user_id for (user_id,) in db.query(RestaurantReview.user_id).filter(
                RestaurantReview.restaurant_id == target.id,
                RestaurantReview.user_id.isnot(None),
            )
        }
        dropped_paths = []
        for review in list(source.reviews):
            if review.user_id is not None and review.user_id in target_reviewers:
                dropped_paths += [photo.path for photo in review.photos]
                db.delete(review)
                continue
            # Through the relationships, so the ORM moves them between
            # the two restaurants' collections
            review.restaurant = target
            for photo in review.photos:
                photo.restaurant = target
        for photo in list(source.photos):
            if photo.review_id is None:
                photo.restaurant = target
                # The target keeps its own featured photo
                photo.is_featured = False
        db.flush()
        return dropped_paths


restaurant_edit_suggestion_crud = RestaurantEditSuggestionCRUDRepository(
    model=RestaurantEditSuggestion)
