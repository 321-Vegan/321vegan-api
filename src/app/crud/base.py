"""
This module contains the base interface for CRUD 
(Create, Read, Update, Delete) operations.
"""
from typing import List, Optional, Type, TypeVar, Tuple

from pydantic import BaseModel
from sqlalchemy import Float, desc, asc, func, case, or_
from sqlalchemy.orm import Session, RelationshipProperty, aliased
from app.models import Base
from app.security import get_password_hash
from app.log import get_logger
from app.crud.filters import buildQueryFilters

ORMModel = TypeVar("ORMModel")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
FilterSchemaType = TypeVar("FilterSchemaType", bound=BaseModel)

log = get_logger(__name__)


class CRUDRepository:
    """Base interface for CRUD operations."""

    def __init__(self, model: Type[ORMModel]) -> None:
        """Initialize the CRUD repository.

        Parameters:
            model (Type[ORMModel]): The ORM model to use for CRUD operations.
            To see models go to app.models module.
        """
        self._model = model
        self._name = model.__name__

    def _query(self, db: Session):
        """
        Base query used by list operations (get_all, get_many).
        Override in subclasses to add loader options (eager loading).

        Parameters:
            db (Session): The database session.

        Returns:
            Query: The base query for the model.
        """
        return db.query(self._model)

    def count(self, db: Session, *args, **kwargs) -> int:
        """
        Retrieves total records from the database.

        Parameters:
            db (Session): The database session object.
        Returns:
            Optional[ORMModel]: The total num of rows.
        """
        log.debug(
            "retrieving total records for %s",
            self._model.__name__,
        )
        query = db.query(self._model)
        # filters
        query = buildQueryFilters(self._model, query, kwargs)

        return query.count()

    def get_one(self, db: Session, *args, **kwargs) -> Optional[ORMModel]:
        """
        Retrieves one record from the database.

        Parameters:
            db (Session): The database session object.
            *args: Variable length argument list used for filter
                e.g. filter(MyClass.name == 'some name')
            **kwargs: Keyword arguments used for filter_by e.g.
                filter_by(name='some name')

        Returns:
            Optional[ORMModel]: The retrieved record, if found.
        """
        log.debug(
            "retrieving one record for %s",
            self._model.__name__,
        )
        return db.query(self._model).filter(*args).filter_by(**kwargs).first()

    def get_one_lookalike(
        self,
        db: Session,
        filter_param: FilterSchemaType,
        min_similarity: float = 0.75
    ) -> Optional[ORMModel]:
        """
        Retrieves one record based on normalized Levenshtein similarity.
        Returns None if no match is similar enough.

        Parameters:
            db (Session): The database session.
            filter_param (FilterSchemaType): Filtering criteria as a Pydantic model.
            min_similarity (float): Minimum similarity ratio (0–1).

        Returns:
            Optional[ORMModel]: The best match, or None if not good enough.
        """
        filter_dict = filter_param.model_dump()
        filter_key, filter_value = next(iter(filter_dict.items()))
        model_attribute = getattr(self._model, filter_key)

        normalized_value = filter_value.strip().lower()

        log.debug(
            "retrieving one lookalike for %s.%s ~= '%s' (min_similarity=%.2f)",
            self._model.__name__,
            filter_key,
            normalized_value,
            min_similarity
        )

        # Levenshtein distance
        lev_dist = func.levenshtein(
            func.lower(func.trim(model_attribute)),
            normalized_value
        )

        # Compute similarity = 1 - (distance / max_length)
        max_len = func.greatest(
            func.length(func.lower(func.trim(model_attribute))),
            len(normalized_value)
        )
        similarity = 1 - (lev_dist.cast(Float) / max_len.cast(Float))

        # Query with similarity calculation
        result = db.query(self._model, similarity.label("similarity"))\
            .order_by(similarity.desc())\
            .first()

        # Only return if similarity passes threshold
        if result and result.similarity >= min_similarity:
            return result[0]
        return None

    def get_by_id(self, db: Session, id: int) -> Optional[ORMModel]:
        """
        Retrieves a record by its ID.

        Parameters:
            db (Session): The database session.
            id (int): The record ID.

        Returns:
            Optional[ORMModel]: The retrieved record, if found.
        """
        return db.query(self._model).filter(self._model.id == id).first()

    def get_all(self, db: Session, *args, **kwargs) -> List[ORMModel]:
        """
        Retrieves all records from the database.

        Parameters:
            db (Session): The database session.
        Returns:
            List[ORMModel]: List of retrieved records.
        """
        log.debug(
            "retrieving all records for %s",
            self._model.__name__
        )
        return self._query(db).all()

    def get_many(
        self, db: Session, *args, skip: int = 0, limit: int = 100, order_by: str = 'created_at', descending: bool = False, **kwargs
    ) -> Tuple[List[ORMModel], int]:
        """
        Retrieves multiple records from the database.

        Parameters:
            db (Session): The database session.
            *args: Variable number of arguments. For example: filter
                db.query(MyClass).filter(MyClass.name == 'some name', MyClass.id > 5)
            skip (int, optional): Number of records to skip. Defaults to 0.
            limit (int, optional): Maximum number of records to retrieve.
                Defaults to 100.
            order_by (str, optional): Field name to order by. Default to 'created_at'.
            descending (bool, optional): Sort direction. Default to False.
            **kwargs: Variable number of keyword arguments. For example: filter_by
                db.query(MyClass).filter_by(name='some name', id > 5)

        Returns:
            Tuple[List[ORMModel], int]: List of retrieved records and number of records.
        """
        log.debug(
            "retrieving many records for %s ordered by %s %s with pagination skip %s and limit %s",
            self._model.__name__,
            order_by,
            'desc' if descending else 'asc',
            skip,
            limit,
        )

        query = self._query(db)

        # filters
        query = buildQueryFilters(self._model, query, kwargs)

        total = query.count()

        # sort by
        model_attribute = getattr(self._model, order_by, getattr(self._model, 'created_at', self._model.id))

        items = query.\
            order_by(desc(model_attribute) if descending else asc(model_attribute)).\
            offset(skip).\
            limit(limit).all()
        return (
            items,
            total
        )

    def get_many_ranked(
        self,
        db: Session,
        search_field: str,
        search_term: str,
        skip: int = 0,
        limit: int = 100,
        **extra_filters,
    ) -> Tuple[List[ORMModel], int]:
        """
        Retrieves multiple records ranked by name relevance: exact > prefix > contains > fuzzy.

        Parameters:
            db (Session): The database session.
            search_field (str): The model field to search on.
            search_term (str): The search string typed by the user.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.
            **extra_filters: Additional filters forwarded to buildQueryFilters.

        Returns:
            Tuple[List[ORMModel], int]: Ranked records and total count.
        """
        col = getattr(self._model, search_field)
        term = search_term.strip().lower()
        col_lower = func.lower(func.trim(col))

        exact = col_lower == term
        prefix = col_lower.like(term + '%')
        contains = col_lower.like('%' + term + '%')

        lev_dist = func.levenshtein(col_lower, term)
        max_len = func.greatest(func.length(col_lower), len(term))
        fuzzy_score = 1 - (lev_dist.cast(Float) / max_len.cast(Float))

        rank = case(
            (exact, 1),
            (prefix, 2),
            (contains, 3),
            else_=4,
        )

        query = db.query(self._model).filter(
            or_(exact, prefix, contains, fuzzy_score >= 0.4)
        )
        query = buildQueryFilters(self._model, query, extra_filters)

        total = query.count()
        items = (
            query
            .order_by(rank, col)
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def create(self, db: Session, obj_create: CreateSchemaType) -> ORMModel:
        """
        Create a new record in the database.

        Parameters:
            db (Session): The database session.
            obj_create (CreateModelType): The data for creating the new record.
            It's a pydantic BaseModel

        Returns:
            ORMModel: The newly created record.
        """
        log.debug(
            "creating record for %s with data %s",
            str(self._model.__name__),
            obj_create.model_dump(),
        )
        obj_create_data = obj_create.model_dump(
            exclude_none=True, exclude_unset=True)
        db_obj = self._model(**obj_create_data)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update(
        self,
        db: Session,
        db_obj: ORMModel,
        obj_update: UpdateSchemaType,
    ) -> ORMModel:
        """
        Updates a record in the database.

        Parameters:
            db (Session): The database session.
            db_obj (ORMModel): The database object to be updated.
            obj_update (UpdateModelType): The updated data for the object
                - it's a pydantic BaseModel.

        Returns:
            ORMModel: The updated database object.
        """
        log.debug(
            "updating record for %s with data %s",
            self._model.__name__,
            obj_update.model_dump(),
        )
        obj_update_data = obj_update.model_dump(
            exclude_unset=True
        )  # exclude_unset=True -
        # do not update fields with None
        for field, value in obj_update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete(self, db: Session, db_obj: ORMModel) -> ORMModel:
        """
        Deletes a record from the database.

        Parameters:
            db (Session): The database session.
            db_obj (ORMModel): The object to be deleted from the database.

        Returns:
            ORMModel: The deleted object.

        """
        log.debug("deleting record for %s with id %s",
                  self._model.__name__, db_obj.id)
        db.delete(db_obj)
        db.commit()
        return db_obj
