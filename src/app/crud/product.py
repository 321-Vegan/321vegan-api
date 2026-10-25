import enum
from typing import List, Optional
from sqlalchemy.orm import Session
from app.log import get_logger
from app.crud.base import CRUDRepository
from app.models.brand import Brand
from app.models.product import Product
from app.models.product_edit import ProductEdit
from app.models.user import User
from app.schemas.product import ProductCreate, ProductUpdate

log = get_logger(__name__)

# Fields recorded in the product history (last_modified_by is the author)
HISTORY_FIELDS = (
    "ean", "name", "description", "problem_description", "brand_id",
    "status", "product_type", "biodynamic", "state",
    "has_non_vegan_old_receipe", "image", "brand_answer",
    "interesting_product_id",
)


def _json_value(value):
    return value.value if isinstance(value, enum.Enum) else value


def _snapshot(product: Product) -> dict:
    return {field: _json_value(getattr(product, field)) for field in HISTORY_FIELDS}


def _brand_name(db: Session, brand_id: Optional[int]) -> Optional[str]:
    brand = db.get(Brand, brand_id) if brand_id is not None else None
    return brand.name if brand else None


def _add_history(
    db: Session, product: Product, before: dict, after: dict, user: User | None
) -> None:
    """
    Add the change between two snapshots to the session, limited to the
    fields that really changed. A brand is recorded with its name so that the
    history stays readable.
    """
    is_creation = not before
    changed = [field for field in HISTORY_FIELDS
               if before.get(field) != after.get(field)]
    if not changed:
        return
    before = {} if is_creation else {
        field: before.get(field) for field in changed}
    after = {field: after.get(field) for field in changed}
    if "brand_id" in changed:
        if not is_creation:
            before["brand_name"] = _brand_name(db, before["brand_id"])
        after["brand_name"] = _brand_name(db, after["brand_id"])
    db.add(ProductEdit(
        product=product,
        user_id=user.id if user else None,
        before=before,
        after=after,
    ))


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
        # The creation is the first history entry. The column defaults
        # aren't set yet: only what was given is recorded.
        _add_history(db, db_obj, {}, {
            field: _json_value(obj_create_data[field])
            for field in HISTORY_FIELDS if obj_create_data.get(field) is not None
        }, user)

        if user:
            user.nb_products_sent = (user.nb_products_sent or 0) + 1
            db.add(user)
        db.commit()
        db.refresh(db_obj)
        if user:
            db.refresh(user)
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
        before = _snapshot(db_obj)
        for field, value in obj_update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        _add_history(db, db_obj, before, _snapshot(db_obj), user)

        if increment_modified:
            user.nb_products_modified = (
                user.nb_products_modified or 0) + 1
        db.commit()
        db.refresh(db_obj)
        db.refresh(user)
        return db_obj

    def get_history(self, db: Session, product_id: int) -> List[ProductEdit]:
        """
        Get the creation and the changes of a product, newest first.

        Parameters:
            db (Session): The database session.
            product_id (int): The product ID.

        Returns:
            List[ProductEdit]: The product history.
        """
        return db.query(ProductEdit).filter(
            ProductEdit.product_id == product_id
        ).order_by(ProductEdit.created_at.desc(), ProductEdit.id.desc()).all()


product_crud = ProductCRUDRepository(model=Product)
