from sqlalchemy.orm import Session
from sqlalchemy import func
from app.crud.base import CRUDRepository
from app.models.product_review import ProductReview, ProductReviewStatus


class ProductReviewCRUDRepository(CRUDRepository):
    def get_product_summary(self, db: Session, product_id: int) -> dict:
        """
        Get review count, average rating and rating distribution for a product
        (approved reviews only).

        Parameters:
            db (Session): The database session.
            product_id (int): The product ID.

        Returns:
            dict: { product_id, review_count, comment_count, rating_avg, rating_distribution }
        """
        rows = db.query(
            self._model.rating,
            func.count(self._model.id).label("review_count"),
            func.count(self._model.comment).label("comment_count"),
        ).filter(
            self._model.product_id == product_id,
            self._model.status == ProductReviewStatus.APPROVED,
        ).group_by(self._model.rating).all()

        distribution = {str(rating): 0 for rating in range(0, 6)}
        review_count = 0
        comment_count = 0
        rating_sum = 0
        for row in rows:
            distribution[str(row.rating)] = row.review_count
            review_count += row.review_count
            comment_count += row.comment_count
            rating_sum += row.rating * row.review_count

        return {
            "product_id": product_id,
            "review_count": review_count,
            "comment_count": comment_count,
            "rating_avg": round(rating_sum / review_count, 1) if review_count else 0.0,
            "rating_distribution": distribution,
        }


product_review_crud = ProductReviewCRUDRepository(model=ProductReview)
