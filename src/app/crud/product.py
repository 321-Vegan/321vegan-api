from typing import Optional
from sqlalchemy.orm import Session
from app.log import get_logger
from app.crud.base import CRUDRepository
from app.models.product import Product
from app.models.user import User
from app.schemas.product import ProductCreate, ProductUpdate
from app.services.xp_service import award_xp, XPAction

log = get_logger(__name__)


class ProductCRUDRepository(CRUDRepository):
    def get_product_by_ean(self, db: Session, ean: str) -> Optional[Product]:
        """
        Get a product by ean.

        Parameters:
            db (Session): The database session.
            ean (str): The ean of the product.

        Returns:
            Optional[Product]: The product found by ean, or None if not found.
        """
        log.debug(
            "retrieving one record for %s",
            self._model.__name__,
        )
        return self.get_one(db, self._model.ean == ean)

    def create(
        self, db: Session, obj_create: ProductCreate, user: User | None
    ) -> Product:
        """Create a new record with ownerin the database.

        Parameters:
            db (Session): The database session.
            obj_create (CreateModelType): The data for creating the new record.
            It's a pydantic BaseModel
            user (User): the owner of the record.

        Returns:
            ORMModel: The newly created record.
        """
        log.debug(
            "creating record for %s with data %s and owner %d",
            self._model.__name__,
            obj_create.model_dump(),
            user.id if user is not None else 0
        )
        obj_create_data = obj_create.model_dump(
            exclude_none=True, exclude_unset=True, exclude_defaults=True,
            exclude={"user_id"}
        )
        if user:
            obj_create_data['last_modified_by'] = user.id
        db_obj = self._model(**obj_create_data)
        db.add(db_obj)

        if user:
            user.nb_products_sent = (user.nb_products_sent or 0) + 1
            db.add(user)
        db.commit()
        db.refresh(db_obj)
        if user:
            db.refresh(user)

        # xp_awarded is transient (not a DB column) : only used to
        # show the gain in the create response, see ProductOut.
        xp_awarded = 0
        if user:
            action_key = (
                XPAction.PRODUCT_INFO_WITH_PHOTO if db_obj.image
                else XPAction.PRODUCT_INFO_NO_PHOTO
            )
            xp_awarded = award_xp(
                db, user, action_key,
                reference_type="product", reference_id=db_obj.id,
            )
        db_obj.xp_awarded = xp_awarded
        return db_obj

    def update(
        self,
        db: Session,
        db_obj: Product,
        obj_update: ProductUpdate,
        user: User,
        increment_modified: bool = True
    ) -> Product:
        """
        Updates a record in the database.

        Parameters:
            db (Session): The database session.
            db_obj (Product): The database object to be updated.
            obj_update (UpdateModelType): The updated data for the object
                - it's a pydantic BaseModel.
            user (User): the updater of the record.

        Returns:
            Product: The updated database object.
        """
        log.debug(
            "updating record for %s with data %s and owner %d",
            self._model.__name__,
            obj_update.model_dump(),
            user.id
        )
        obj_update_data = obj_update.model_dump(
            exclude_unset=True
        )  # exclude_unset=True -
        # do not update fields with None
        obj_update_data['last_modified_by'] = user.id
        for field, value in obj_update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)

        if increment_modified:
            user.nb_products_modified = (
                user.nb_products_modified or 0) + 1
        db.commit()
        db.refresh(db_obj)
        db.refresh(user)
        return db_obj


product_crud = ProductCRUDRepository(model=Product)
