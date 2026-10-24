from typing import Optional
from sqlalchemy.orm import Session, selectinload, lazyload
from app.crud.base import CRUDRepository
from app.models.interesting_product import InterestingProduct
from app.models.product import Product


class InterestingProductCRUDRepository(CRUDRepository):
    def _query(self, db: Session):
        """
        Eager load the relationships serialized by InterestingProductOut to avoid
        N+1 queries on list endpoints. Product checkings (lazy="selectin" by default)
        are not part of the output, so they are not loaded.
        """
        return db.query(self._model).options(
            selectinload(self._model.brand),
            selectinload(self._model.category),
            selectinload(self._model.product).lazyload(Product.checkings),
            selectinload(self._model.alternative_products).lazyload(
                Product.checkings),
        )

    def get_by_ean(self, db: Session, ean: str) -> Optional[InterestingProduct]:
        """
        Get an interesting product by EAN.

        Parameters:
            db (Session): The database session.
            ean (str): The EAN of the product.

        Returns:
            Optional[InterestingProduct]: The product found by EAN, or None if not found.
        """
        return self.get_one(db, self._model.ean == ean)


interesting_product_crud = InterestingProductCRUDRepository(model=InterestingProduct)
