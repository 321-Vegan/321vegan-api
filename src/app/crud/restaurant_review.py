from sqlalchemy.orm import Session
from sqlalchemy import func
from app.crud.base import CRUDRepository
from app.models.restaurant_photo import RestaurantPhotoStatus
from app.models.restaurant_review import RestaurantReview, RestaurantReviewStatus
from app.schemas.restaurant_review import CRITERIA


class RestaurantReviewCRUDRepository(CRUDRepository):
    def set_status(self, db: Session, review: RestaurantReview, status: RestaurantReviewStatus) -> RestaurantReview:
        """
        Set the status of a review and of its photos, which follow it.

        Parameters:
            db (Session): The database session.
            review (RestaurantReview): The review.
            status (RestaurantReviewStatus): The new status.

        Returns:
            RestaurantReview: The updated review.
        """
        review.status = status
        for photo in review.photos:
            photo.status = RestaurantPhotoStatus(status.value)
        db.add(review)
        db.commit()
        db.refresh(review)
        return review

    def get_restaurant_summary(self, db: Session, restaurant_id: int) -> dict:
        """
        Get review count, average overall rating, its distribution and the
        average of each detailed rating for a restaurant (approved reviews only).

        Parameters:
            db (Session): The database session.
            restaurant_id (int): The restaurant ID.

        Returns:
            dict: { restaurant_id, review_count, comment_count, rating_avg,
                    rating_distribution, criteria }
        """
        approved = (
            self._model.restaurant_id == restaurant_id,
            self._model.status == RestaurantReviewStatus.APPROVED,
        )
        rows = db.query(
            self._model.rating,
            func.count(self._model.id).label("review_count"),
            func.count(self._model.comment).label("comment_count"),
        ).filter(*approved).group_by(self._model.rating).all()

        distribution = {str(rating): 0 for rating in range(1, 6)}
        review_count = 0
        comment_count = 0
        rating_sum = 0
        for row in rows:
            distribution[str(row.rating)] = row.review_count
            review_count += row.review_count
            comment_count += row.comment_count
            rating_sum += row.rating * row.review_count

        columns = []
        for column_name in CRITERIA.values():
            column = getattr(self._model, column_name)
            columns += [func.avg(column), func.count(column)]
        stats = db.query(*columns).filter(*approved).one()
        criteria = {}
        for index, key in enumerate(CRITERIA):
            avg, count = stats[2 * index], stats[2 * index + 1]
            criteria[key] = {
                "rating_avg": round(float(avg), 1) if avg is not None else None,
                "rating_count": count or 0,
            }

        return {
            "restaurant_id": restaurant_id,
            "review_count": review_count,
            "comment_count": comment_count,
            "rating_avg": round(rating_sum / review_count, 1) if review_count else 0.0,
            "rating_distribution": distribution,
            "criteria": criteria,
        }


restaurant_review_crud = RestaurantReviewCRUDRepository(model=RestaurantReview)
