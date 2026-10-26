from sqlalchemy.orm import Session
from sqlalchemy import func
from app.crud.base import CRUDRepository
from app.models.restaurant_photo import RestaurantPhotoStatus
from app.models.restaurant_review import RestaurantPriceRange, RestaurantReview, RestaurantReviewStatus
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
        Get review count, average overall rating, its distribution, the
        average of each detailed rating and the price ranges (the most chosen
        and their distribution) for a restaurant (approved reviews only).

        Parameters:
            db (Session): The database session.
            restaurant_id (int): The restaurant ID.

        Returns:
            dict: { restaurant_id, review_count, comment_count, rating_avg,
                    rating_distribution, criteria, price_range,
                    price_range_distribution }
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

        price_rows = db.query(
            self._model.price_range, func.count(self._model.id)
        ).filter(*approved, self._model.price_range.isnot(None)).group_by(
            self._model.price_range).all()
        price_counts = dict(price_rows)
        price_distribution = {
            price_range.value: price_counts.get(price_range, 0)
            for price_range in RestaurantPriceRange
        }
        # The most chosen; on a tie, the cheaper (ranges in price order)
        most_chosen = max(
            (price_range for price_range in RestaurantPriceRange
             if price_counts.get(price_range)),
            key=lambda price_range: price_counts[price_range],
            default=None,
        )

        return {
            "restaurant_id": restaurant_id,
            "review_count": review_count,
            "comment_count": comment_count,
            "rating_avg": round(rating_sum / review_count, 1) if review_count else 0.0,
            "rating_distribution": distribution,
            "criteria": criteria,
            "price_range": most_chosen.value if most_chosen else None,
            "price_range_distribution": price_distribution,
        }


restaurant_review_crud = RestaurantReviewCRUDRepository(model=RestaurantReview)
