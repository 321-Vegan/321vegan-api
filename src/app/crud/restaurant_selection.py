from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from app.crud.base import CRUDRepository
from app.models.restaurant import Restaurant
from app.models.restaurant_selection import (
    RestaurantSelection,
    RestaurantSelectionItem,
    RestaurantSelectionShare,
    RestaurantSelectionShareStatus,
)

# Shares a recipient still has (not refused or removed)
KEPT_SHARE_STATUSES = (RestaurantSelectionShareStatus.PENDING,
                       RestaurantSelectionShareStatus.ACCEPTED)


def is_restaurant_visible(restaurant: Restaurant, user_id: int) -> bool:
    """Same rule as the saved restaurants: validated, or created by the user."""
    return restaurant.date_deleted is None and (
        restaurant.validated or restaurant.created_by == user_id)


def visible_items(selection: RestaurantSelection, user_id: int) -> List[RestaurantSelectionItem]:
    """The items of a selection the user can see, in order."""
    return [item for item in selection.items
            if is_restaurant_visible(item.restaurant, user_id)]


class RestaurantSelectionCRUDRepository(CRUDRepository):
    def count_for_user(self, db: Session, user_id: int) -> int:
        """
        Count the selections of a user.

        Parameters:
            db (Session): The database session.
            user_id (int): The owner ID.

        Returns:
            int: The number of selections.
        """
        return db.query(self._model).filter(
            self._model.user_id == user_id).count()

    def get_owned(
        self,
        db: Session,
        user_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[RestaurantSelection], int]:
        """
        Get the selections of a user, last updated first.

        Parameters:
            db (Session): The database session.
            user_id (int): The owner ID.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.

        Returns:
            Tuple[List[RestaurantSelection], int]: The selections and total count.
        """
        query = db.query(self._model).filter(self._model.user_id == user_id)
        total = query.count()
        selections = query.order_by(
            self._model.updated_at.desc()).offset(skip).limit(limit).all()
        return selections, total

    def get_visible_restaurants(
        self, db: Session, restaurant_ids: List[int], user_id: int
    ) -> Dict[int, Restaurant]:
        """
        Get the restaurants among some IDs the user can put in a selection.

        Parameters:
            db (Session): The database session.
            restaurant_ids (List[int]): The restaurant IDs.
            user_id (int): The user ID.

        Returns:
            Dict[int, Restaurant]: The visible restaurants by ID.
        """
        if not restaurant_ids:
            return {}
        restaurants = db.query(Restaurant).filter(
            Restaurant.id.in_(restaurant_ids),
            Restaurant.date_deleted.is_(None),
            or_(Restaurant.validated.is_(True),
                Restaurant.created_by == user_id),
        ).all()
        return {restaurant.id: restaurant for restaurant in restaurants}

    def create_for_user(
        self,
        db: Session,
        user_id: int,
        title: str,
        description: Optional[str],
        items: List[dict],
    ) -> RestaurantSelection:
        """
        Create a selection.

        Parameters:
            db (Session): The database session.
            user_id (int): The owner ID.
            title (str): The title.
            description (Optional[str]): The description.
            items (List[dict]): The restaurants ({restaurant_id, note}), in order.

        Returns:
            RestaurantSelection: The created selection.
        """
        selection = self._model(
            user_id=user_id, title=title, description=description)
        selection.items = [
            RestaurantSelectionItem(
                restaurant_id=item["restaurant_id"], note=item.get("note"), position=position)
            for position, item in enumerate(items)
        ]
        db.add(selection)
        db.commit()
        db.refresh(selection)
        return selection

    def update_selection(
        self, db: Session, selection: RestaurantSelection, changes: dict
    ) -> RestaurantSelection:
        """
        Update a selection. Items, when given, replace the whole list: the
        kept restaurants are updated in place (the pair selection/restaurant
        is unique, so deleting and adding them back in one flush would clash).

        Parameters:
            db (Session): The database session.
            selection (RestaurantSelection): The selection.
            changes (dict): The changed fields (title, description, items).

        Returns:
            RestaurantSelection: The updated selection.
        """
        for field in ("title", "description"):
            if field in changes:
                setattr(selection, field, changes[field])
        if changes.get("items") is not None:
            current = {item.restaurant_id: item for item in selection.items}
            new_items = []
            for position, item_in in enumerate(changes["items"]):
                item = current.get(item_in["restaurant_id"])
                if item is None:
                    item = RestaurantSelectionItem(
                        restaurant_id=item_in["restaurant_id"])
                item.position = position
                item.note = item_in.get("note")
                new_items.append(item)
            selection.items = new_items
        # The items alone don't touch the selection row
        selection.updated_at = datetime.now()
        db.commit()
        db.refresh(selection)
        return selection

    def add_restaurant(
        self, db: Session, selection: RestaurantSelection, restaurant_id: int
    ) -> None:
        """
        Add a restaurant at the end of a selection; nothing to do when already in.

        Parameters:
            db (Session): The database session.
            selection (RestaurantSelection): The selection.
            restaurant_id (int): The restaurant ID.
        """
        if any(item.restaurant_id == restaurant_id for item in selection.items):
            return
        position = max((item.position for item in selection.items),
                       default=-1) + 1
        selection.items.append(RestaurantSelectionItem(
            restaurant_id=restaurant_id, position=position))
        selection.updated_at = datetime.now()
        db.commit()

    def remove_restaurant(
        self, db: Session, selection: RestaurantSelection, restaurant_id: int
    ) -> None:
        """
        Remove a restaurant from a selection, if there.

        Parameters:
            db (Session): The database session.
            selection (RestaurantSelection): The selection.
            restaurant_id (int): The restaurant ID.
        """
        kept = [item for item in selection.items
                if item.restaurant_id != restaurant_id]
        if len(kept) == len(selection.items):
            return
        for position, item in enumerate(kept):
            item.position = position
        selection.items = kept
        selection.updated_at = datetime.now()
        db.commit()


class RestaurantSelectionShareCRUDRepository(CRUDRepository):
    def get_for(
        self, db: Session, selection_id: int, recipient_id: int
    ) -> Optional[RestaurantSelectionShare]:
        """
        Get the share of a selection with a user.

        Parameters:
            db (Session): The database session.
            selection_id (int): The selection ID.
            recipient_id (int): The recipient ID.

        Returns:
            Optional[RestaurantSelectionShare]: The share, if sent.
        """
        return db.query(self._model).filter(
            self._model.selection_id == selection_id,
            self._model.recipient_id == recipient_id,
        ).first()

    def send(self, db: Session, selection_id: int, recipient_id: int) -> bool:
        """
        Send a selection to a user. Nothing to do when already sent, even if
        they refused or removed it.

        Parameters:
            db (Session): The database session.
            selection_id (int): The selection ID.
            recipient_id (int): The recipient ID.

        Returns:
            bool: Whether it was sent now.
        """
        if self.get_for(db, selection_id, recipient_id) is not None:
            return False
        db.add(self._model(selection_id=selection_id,
               recipient_id=recipient_id))
        db.commit()
        return True

    def count_accepted(self, db: Session, selection_ids: List[int]) -> Dict[int, int]:
        """
        Count the users who accepted each of some selections.

        Parameters:
            db (Session): The database session.
            selection_ids (List[int]): The selection IDs.

        Returns:
            Dict[int, int]: The number of acceptances by selection ID (missing
                when none).
        """
        if not selection_ids:
            return {}
        rows = db.query(self._model.selection_id, func.count(self._model.id)).filter(
            self._model.selection_id.in_(selection_ids),
            self._model.status == RestaurantSelectionShareStatus.ACCEPTED,
        ).group_by(self._model.selection_id).all()
        return dict(rows)

    def count_sent_since(self, db: Session, owner_id: int, since: datetime) -> int:
        """
        Count the selections a user sent since a date.

        Parameters:
            db (Session): The database session.
            owner_id (int): The sender ID.
            since (datetime): The start date.

        Returns:
            int: The number of shares.
        """
        return db.query(self._model).join(
            RestaurantSelection, RestaurantSelection.id == self._model.selection_id
        ).filter(
            RestaurantSelection.user_id == owner_id,
            self._model.created_at >= since,
        ).count()

    def get_received(
        self,
        db: Session,
        recipient_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[RestaurantSelectionShare], int]:
        """
        Get the selections sent to a user that they still have: pending ones
        first, then the accepted ones, last sent first.

        Parameters:
            db (Session): The database session.
            recipient_id (int): The recipient ID.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.

        Returns:
            Tuple[List[RestaurantSelectionShare], int]: The shares and total count.
        """
        query = db.query(self._model).filter(
            self._model.recipient_id == recipient_id,
            self._model.status.in_(KEPT_SHARE_STATUSES),
        )
        total = query.count()
        pending_first = case(
            (self._model.status == RestaurantSelectionShareStatus.PENDING, 0), else_=1)
        shares = query.order_by(
            pending_first, self._model.created_at.desc()).offset(skip).limit(limit).all()
        return shares, total

    def count_unread(self, db: Session, recipient_id: int) -> int:
        """
        Count the pending selections a user has not seen yet.

        Parameters:
            db (Session): The database session.
            recipient_id (int): The recipient ID.

        Returns:
            int: The number of unread selections.
        """
        return db.query(self._model).filter(
            self._model.recipient_id == recipient_id,
            self._model.status == RestaurantSelectionShareStatus.PENDING,
            self._model.seen_at.is_(None),
        ).count()

    def mark_all_seen(self, db: Session, recipient_id: int) -> None:
        """
        Mark every selection sent to a user as seen.

        Parameters:
            db (Session): The database session.
            recipient_id (int): The recipient ID.
        """
        db.query(self._model).filter(
            self._model.recipient_id == recipient_id,
            self._model.seen_at.is_(None),
        ).update({self._model.seen_at: datetime.now()}, synchronize_session=False)
        db.commit()

    def answer(
        self,
        db: Session,
        share: RestaurantSelectionShare,
        status: RestaurantSelectionShareStatus,
    ) -> None:
        """
        Accept, refuse or remove a selection received; it counts as seen.

        Parameters:
            db (Session): The database session.
            share (RestaurantSelectionShare): The share.
            status (RestaurantSelectionShareStatus): ACCEPTED or DECLINED.
        """
        now = datetime.now()
        share.status = status
        share.responded_at = now
        if share.seen_at is None:
            share.seen_at = now
        db.commit()


restaurant_selection_crud = RestaurantSelectionCRUDRepository(
    model=RestaurantSelection)
restaurant_selection_share_crud = RestaurantSelectionShareCRUDRepository(
    model=RestaurantSelectionShare)
