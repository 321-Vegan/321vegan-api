import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params
from app.crud import user_crud
from app.crud.restaurant_selection import (
    KEPT_SHARE_STATUSES,
    SORT_POPULAR,
    SORT_RECENT,
    restaurant_selection_crud,
    restaurant_selection_share_crud,
    visible_items,
)
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.models.restaurant_selection import (
    RestaurantSelection,
    RestaurantSelectionShare,
    RestaurantSelectionShareStatus,
)
from app.services.s3_file_manager import s3_file_manager
from app.schemas.restaurant import RestaurantMapOut, RestaurantPhotoOut
from app.schemas.restaurant_selection import (
    MAX_SELECTION_RESTAURANTS,
    RestaurantSelectionCreate,
    RestaurantSelectionItemOut,
    RestaurantSelectionOut,
    RestaurantSelectionSend,
    RestaurantSelectionSendOut,
    RestaurantSelectionSummaryOut,
    RestaurantSelectionSummaryOutPaginated,
    RestaurantSelectionUnreadCountOut,
    RestaurantSelectionUpdate,
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])

MAX_SELECTIONS_PER_USER = 50
MAX_COVER_PHOTOS = 4
# Selections a user can send per day, against spam
MAX_SENDS_PER_DAY = 30


def _summary_fields(
    selection: RestaurantSelection,
    user: User,
    share: Optional[RestaurantSelectionShare] = None,
    accepted_count: Optional[int] = None,
) -> dict:
    """
    Fields of a selection as seen by the user: its owner (with
    accepted_count), or the recipient of share.
    """
    items = visible_items(selection, user.id)
    cover_photos = [
        RestaurantPhotoOut.model_validate(item.restaurant.featured_photo)
        for item in items if item.restaurant.featured_photo is not None
    ][:MAX_COVER_PHOTOS]
    fields = {
        "id": selection.id,
        "title": selection.title,
        "description": selection.description,
        "owner_id": selection.user_id,
        "owner_nickname": selection.user.nickname,
        "is_owner": selection.user_id == user.id,
        "is_public": selection.is_public,
        "published_at": selection.published_at,
        "restaurant_ids": [item.restaurant_id for item in items],
        "cover_path": selection.cover_path,
        "cover_photos": cover_photos,
        "created_at": selection.created_at,
        "updated_at": selection.updated_at,
        "accepted_count": accepted_count,
    }
    if share is not None:
        fields.update({
            "share_status": share.status.value,
            "is_seen": share.seen_at is not None,
            "shared_at": share.created_at,
        })
    return fields


def _summary_out(
    selection: RestaurantSelection,
    user: User,
    share: Optional[RestaurantSelectionShare] = None,
    accepted_count: Optional[int] = None,
) -> RestaurantSelectionSummaryOut:
    return RestaurantSelectionSummaryOut(
        **_summary_fields(selection, user, share, accepted_count))


def _owner_selection_out(
    db: Session, selection: RestaurantSelection, user: User
) -> RestaurantSelectionOut:
    """The selection for its owner, with how many users accepted it."""
    accepted = restaurant_selection_share_crud.count_accepted(db, [selection.id])
    return _selection_out(db, selection, user, accepted_count=accepted.get(selection.id, 0))


def _selection_out(
    db: Session,
    selection: RestaurantSelection,
    user: User,
    share: Optional[RestaurantSelectionShare] = None,
    accepted_count: Optional[int] = None,
) -> RestaurantSelectionOut:
    """
    The selection with its restaurants the user can see, in order, and the
    rating its author gave each in their review.
    """
    ratings = restaurant_selection_crud.get_author_ratings(db, selection)
    items = [
        RestaurantSelectionItemOut(
            restaurant=RestaurantMapOut.model_validate(item.restaurant),
            note=item.note,
            author_rating=ratings.get(item.restaurant_id),
        )
        for item in visible_items(selection, user.id)
    ]
    return RestaurantSelectionOut(
        **_summary_fields(selection, user, share, accepted_count), items=items)


def _get_selection(db: Session, id: int) -> RestaurantSelection:
    """
    Raises:
        HTTPException: If the selection does not exist.
    """
    selection = restaurant_selection_crud.get_by_id(db, id)
    if selection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Selection not found"
        )
    return selection


def _get_own_selection(db: Session, id: int, user: User) -> RestaurantSelection:
    """
    Raises:
        HTTPException: If the selection does not exist or is not the user's.
    """
    selection = _get_selection(db, id)
    if selection.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Selection not found"
        )
    return selection


def _get_received_share(db: Session, id: int, user: User) -> RestaurantSelectionShare:
    """
    The selection sent to the user, that they still have (pending or accepted).

    Raises:
        HTTPException: If it was not sent to the user, or they refused or removed it.
    """
    share = restaurant_selection_share_crud.get_for(db, id, user.id)
    if share is None or share.status not in KEPT_SHARE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Selection not found"
        )
    return share


def _check_restaurants(db: Session, restaurant_ids: List[int], user: User) -> None:
    """
    Raises:
        HTTPException: If one of the restaurants is not visible to the user.
    """
    visible = restaurant_selection_crud.get_visible_restaurants(
        db, restaurant_ids, user.id)
    missing = [id for id in restaurant_ids if id not in visible]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Restaurant not found: {', '.join(map(str, missing))}",
        )


def _paginated(items: list, total: int, skip: int, size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": (total + size - 1) // size,
    }


@router.get(
    "/mine",
    response_model=RestaurantSelectionSummaryOutPaginated,
    status_code=status.HTTP_200_OK,
)
def fetch_my_selections(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionSummaryOutPaginated:
    """
    Fetch the selections of the current user, last updated first.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionSummaryOutPaginated: The selections with pagination data.
    """
    skip, size = pagination_params
    selections, total = restaurant_selection_crud.get_owned(
        db, current_user.id, skip=skip, limit=size)
    accepted = restaurant_selection_share_crud.count_accepted(
        db, [selection.id for selection in selections])
    return _paginated([_summary_out(selection, current_user,
                                    accepted_count=accepted.get(selection.id, 0))
                       for selection in selections],
                      total, skip, size)


@router.get(
    "/received",
    response_model=RestaurantSelectionSummaryOutPaginated,
    status_code=status.HTTP_200_OK,
)
def fetch_received_selections(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionSummaryOutPaginated:
    """
    Fetch the selections sent to the current user that they still have:
    pending ones first (to accept or refuse), then the accepted ones, last
    sent first.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionSummaryOutPaginated: The selections with pagination data.
    """
    skip, size = pagination_params
    shares, total = restaurant_selection_share_crud.get_received(
        db, current_user.id, skip=skip, limit=size)
    return _paginated([_summary_out(share.selection, current_user, share) for share in shares],
                      total, skip, size)


@router.get(
    "/received/unread-count",
    response_model=RestaurantSelectionUnreadCountOut,
    status_code=status.HTTP_200_OK,
)
def fetch_unread_selection_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionUnreadCountOut:
    """
    Count the selections sent to the current user, pending and not seen yet.

    Parameters:
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionUnreadCountOut: The number of unread selections.
    """
    return {"count": restaurant_selection_share_crud.count_unread(db, current_user.id)}


@router.put("/received/seen", status_code=status.HTTP_204_NO_CONTENT)
def mark_received_selections_seen(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Mark every selection sent to the current user as seen (they opened the
    list), pending ones included.

    Parameters:
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    restaurant_selection_share_crud.mark_all_seen(db, current_user.id)


@router.get(
    "/public",
    response_model=RestaurantSelectionSummaryOutPaginated,
    status_code=status.HTTP_200_OK,
)
def fetch_public_selections(
    sort: Literal["recent", "popular"] = Query(default=SORT_RECENT),
    search: Optional[str] = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionSummaryOutPaginated:
    """
    Fetch the public selections having a restaurant, that any user can take:
    the most recently published first, or the most taken first (popular).

    Parameters:
        sort (str): "recent" or "popular".
        search (Optional[str]): Keep the ones whose title contains it.
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionSummaryOutPaginated: The selections with pagination data.
    """
    skip, size = pagination_params
    selections, total = restaurant_selection_crud.get_public(
        db, sort=sort, search=search, skip=skip, limit=size)
    ids = [selection.id for selection in selections]
    accepted = restaurant_selection_share_crud.count_accepted(db, ids)
    shares = restaurant_selection_share_crud.get_for_many(
        db, ids, current_user.id)
    return _paginated([_summary_out(selection, current_user, shares.get(selection.id),
                                    accepted_count=accepted.get(selection.id, 0))
                       for selection in selections],
                      total, skip, size)


@router.post(
    "/",
    response_model=RestaurantSelectionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_selection(
    selection_in: RestaurantSelectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionOut:
    """
    Create a selection of restaurants, in the given order. A public one
    needs a restaurant.

    Parameters:
        selection_in (RestaurantSelectionCreate): The selection data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionOut: The created selection.
    """
    if restaurant_selection_crud.count_for_user(db, current_user.id) >= MAX_SELECTIONS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You cannot have more than {MAX_SELECTIONS_PER_USER} selections",
        )
    items = [item.model_dump() for item in selection_in.items]
    if selection_in.is_public and not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add a restaurant to the selection before publishing it",
        )
    _check_restaurants(db, [item["restaurant_id"]
                       for item in items], current_user)
    selection = restaurant_selection_crud.create_for_user(
        db, current_user.id, selection_in.title, selection_in.description, items,
        is_public=selection_in.is_public)
    log.info(
        f"Restaurant selection created: {selection.id} by user {current_user.id}")
    return _selection_out(db, selection, current_user, accepted_count=0)


@router.get(
    "/{id}",
    response_model=RestaurantSelectionOut,
    status_code=status.HTTP_200_OK,
)
def fetch_selection(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionOut:
    """
    Fetch a selection with its restaurants: for its owner, a user it was
    sent to (pending or accepted), or anyone when public. Permanently closed
    restaurants are kept so the app can show them as closed.

    Parameters:
        id (int): The ID of the selection.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionOut: The selection.
    """
    selection = _get_selection(db, id)
    if selection.user_id == current_user.id:
        return _owner_selection_out(db, selection, current_user)
    if not selection.is_public:
        share = _get_received_share(db, id, current_user)
        return _selection_out(db, selection, current_user, share)
    share = restaurant_selection_share_crud.get_for(db, id, current_user.id)
    accepted = restaurant_selection_share_crud.count_accepted(db, [selection.id])
    return _selection_out(db, selection, current_user, share,
                          accepted_count=accepted.get(selection.id, 0))


@router.put(
    "/{id}",
    response_model=RestaurantSelectionOut,
    status_code=status.HTTP_200_OK,
)
def update_selection(
    id: int,
    selection_in: RestaurantSelectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionOut:
    """
    Update a selection (its owner only). The items, when given, replace the
    whole list: restaurants, order and notes. The users it was sent to see
    the changes. It can be made public (with a restaurant), but a public
    selection cannot be made private again.

    Parameters:
        id (int): The ID of the selection.
        selection_in (RestaurantSelectionUpdate): The changed fields.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionOut: The updated selection.
    """
    selection = _get_own_selection(db, id, current_user)
    changes = selection_in.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The title cannot be empty",
        )
    if changes.get("is_public") is False and selection.is_public:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A public selection cannot be made private",
        )
    items = changes.get("items")
    publishing = changes.get("is_public") is True and not selection.is_public
    if publishing and not (items if items is not None else selection.items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add a restaurant to the selection before publishing it",
        )
    if items is not None:
        _check_restaurants(
            db, [item["restaurant_id"] for item in items], current_user)
    updated = restaurant_selection_crud.update_selection(db, selection, changes)
    log.info(
        f"Restaurant selection updated: {id} by user {current_user.id}, fields {list(changes)}")
    return _owner_selection_out(db, updated, current_user)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_selection(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a selection (its owner only); the users it was sent to lose it.

    Parameters:
        id (int): The ID of the selection.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    selection = _get_own_selection(db, id, current_user)
    cover_path = selection.cover_path
    restaurant_selection_crud.delete(db, selection)
    if cover_path:
        s3_file_manager.delete_file(cover_path)
    log.info(
        f"Restaurant selection deleted: {id} by user {current_user.id}")


@router.put("/{id}/restaurants/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_restaurant_to_selection(
    id: int,
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Add a restaurant at the end of a selection (its owner only); no-op when
    already in.

    Parameters:
        id (int): The ID of the selection.
        restaurant_id (int): The ID of the restaurant.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    selection = _get_own_selection(db, id, current_user)
    _check_restaurants(db, [restaurant_id], current_user)
    already_in = any(item.restaurant_id ==
                     restaurant_id for item in selection.items)
    if not already_in and len(selection.items) >= MAX_SELECTION_RESTAURANTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A selection cannot have more than {MAX_SELECTION_RESTAURANTS} restaurants",
        )
    restaurant_selection_crud.add_restaurant(db, selection, restaurant_id)


@router.delete("/{id}/restaurants/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_restaurant_from_selection(
    id: int,
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Remove a restaurant from a selection (its owner only); no-op when not in.

    Parameters:
        id (int): The ID of the selection.
        restaurant_id (int): The ID of the restaurant.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    selection = _get_own_selection(db, id, current_user)
    restaurant_selection_crud.remove_restaurant(db, selection, restaurant_id)


@router.post(
    "/{id}/send",
    response_model=RestaurantSelectionSendOut,
    status_code=status.HTTP_200_OK,
)
def send_selection(
    id: int,
    send_in: RestaurantSelectionSend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionSendOut:
    """
    Send a selection (its owner only) to a user, who can accept or refuse
    it: by email, or by friend code.
    - By email, the answer is the same whether the email has an account or
      not, so that it doesn't tell who uses the app.
    - By friend code, the recipient's nickname is given back, to check it
      went to the right person; an unknown code is a 404.
    Sending it again to the same user does nothing while it's pending or
    accepted; if they refused or removed it, it's pending again.

    Parameters:
        id (int): The ID of the selection.
        send_in (RestaurantSelectionSend): The recipient's email or friend code.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionSendOut: The recipient's nickname, by friend code.
    """
    selection = _get_own_selection(db, id, current_user)
    if not visible_items(selection, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add a restaurant to the selection before sending it",
        )
    by_code = send_in.friend_code is not None
    if by_code:
        recipient = user_crud.get_user_by_friend_code(db, send_in.friend_code)
        if recipient is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No user has this friend code",
            )
        is_self = recipient.id == current_user.id
    else:
        is_self = send_in.email.lower() == current_user.email.lower()
    if is_self:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a selection to yourself",
        )
    since = datetime.now() - timedelta(days=1)
    if restaurant_selection_share_crud.count_sent_since(db, current_user.id, since) >= MAX_SENDS_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You cannot send more than {MAX_SENDS_PER_DAY} selections per day",
        )
    if not by_code:
        recipient = user_crud.get_user_by_email(db, email=send_in.email)
        if recipient is None:
            log.info(
                f"Restaurant selection {id} sent by user {current_user.id} to an unknown email")
            return {"recipient_nickname": None}
    if restaurant_selection_share_crud.send(db, selection.id, recipient.id):
        log.info(
            f"Restaurant selection {id} sent by user {current_user.id} to user {recipient.id}")
    return {"recipient_nickname": recipient.nickname if by_code else None}


@router.put("/{id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_selection(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Accept a selection sent to the current user, or take a public one: it
    shows with their saved restaurants. No-op when already accepted.

    Parameters:
        id (int): The ID of the selection.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    selection = _get_selection(db, id)
    if selection.is_public:
        if selection.user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot take your own selection",
            )
        restaurant_selection_share_crud.take(db, id, current_user.id)
        log.info(f"Public restaurant selection {id} taken by user {current_user.id}")
        return
    share = _get_received_share(db, id, current_user)
    if share.status != RestaurantSelectionShareStatus.ACCEPTED:
        restaurant_selection_share_crud.answer(
            db, share, RestaurantSelectionShareStatus.ACCEPTED)


@router.delete("/{id}/received", status_code=status.HTTP_204_NO_CONTENT)
def remove_received_selection(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Refuse a selection sent to the current user, or remove it after
    accepting it. It won't come back if its owner sends it again.

    Parameters:
        id (int): The ID of the selection.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    share = _get_received_share(db, id, current_user)
    restaurant_selection_share_crud.answer(
        db, share, RestaurantSelectionShareStatus.DECLINED)


@router.put(
    "/{id}/cover",
    response_model=RestaurantSelectionOut,
    status_code=status.HTTP_200_OK,
)
def set_selection_cover(
    id: int,
    file: UploadFile = File(...,
                            description="Image (JPG, PNG, WebP max 5MB)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSelectionOut:
    """
    Set the cover image of a selection (its owner only), replacing the
    previous one. It is stored in the bucket under selections/{id}/ and shown
    right away, even on a public selection.

    Parameters:
        id (int): The ID of the selection.
        file (UploadFile): Image file (JPG, PNG, WebP, max 5MB).
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSelectionOut: The updated selection.
    """
    selection = _get_own_selection(db, id, current_user)
    file_extension = Path(file.filename or "").suffix.lower()
    object_name = f"selections/{selection.id}/cover_{uuid.uuid4().hex}{file_extension}"
    s3_file_manager.upload_image(object_name, file)
    previous = restaurant_selection_crud.set_cover(db, selection, object_name)
    if previous:
        s3_file_manager.delete_file(previous)
    log.info(
        f"Restaurant selection cover set: {object_name} by user {current_user.id}")
    return _owner_selection_out(db, selection, current_user)


@router.delete("/{id}/cover", status_code=status.HTTP_204_NO_CONTENT)
def remove_selection_cover(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Remove the cover image of a selection (its owner only): the featured
    photos of its restaurants show instead.

    Parameters:
        id (int): The ID of the selection.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    selection = _get_own_selection(db, id, current_user)
    previous = restaurant_selection_crud.set_cover(db, selection, None)
    if previous:
        s3_file_manager.delete_file(previous)
        log.info(
            f"Restaurant selection cover removed: {id} by user {current_user.id}")

