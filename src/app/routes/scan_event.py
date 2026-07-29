import json
from typing import Annotated, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_current_active_user_or_client, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud import scan_event_crud, user_crud
from app.crud.shop import shop_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import ScanEvent, User, ApiClient
from app.schemas.scan_event import ScanEventCreate, ScanEventOut, ScanEventUpdate, ScanEventOutPaginated, ScanEventFilters, ConfirmShopRequest, NearbyShopOut
from app.schemas.shop import ShopCreate
from app.schemas.xp import XPGrant
from app.services.openstreetmap import osm_service
from app.services.xp_service import award_xp, XPAction

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user_or_client)])


def _award_first_in_shop_bonus(
    db: Session, event: ScanEvent, scan_user: User
) -> Optional[XPGrant]:
    """
    Award the Vegandex "first to find this product in this shop" bonus,
    if `event` has a shop_id and nobody has scanned this product there
    before.

    Called both right after creation (when the shop was already resolved
    inline) and from confirm_shop() (when shop resolution needed user
    disambiguation, so shop_id wasn't known yet at creation time) — the
    check can only run once shop_id is actually set.

    Parameters:
        db (Session): The database session.
        event (ScanEvent): The scan event, with shop_id already set.
        scan_user (User): The user to credit.

    Returns:
        Optional[XPGrant]: The grant if awarded, else None.
    """
    if not event.shop_id:
        return None
    if scan_event_crud.ean_already_found_at_shop(
        db, event.ean, event.shop_id, exclude_event_id=event.id,
    ):
        return None
    xp = award_xp(
        db, scan_user, XPAction.VEGANDEX_SCAN_FIRST_IN_SHOP,
        reference_type="scan_event", reference_id=event.id,
    )
    if not xp:
        return None
    return XPGrant(action_key=XPAction.VEGANDEX_SCAN_FIRST_IN_SHOP, xp=xp)


@router.get(
    "/", response_model=List[Optional[ScanEventOut]], status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def fetch_all_scan_events(db: Session = Depends(get_db)) -> List[Optional[ScanEventOut]]:
    """
    Fetch all scan events.

    This function fetches all scan events from the database.

    Admin only: scan events carry the user's identity and geolocation.

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[ScanEventOut]]: The list of scan events fetched from the database.
    """
    return scan_event_crud.get_all(db)


@router.get(
    "/search", response_model=Optional[ScanEventOutPaginated], status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def fetch_paginated_scan_events(
    filter_params: ScanEventFilters = Depends(),
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
) -> Optional[ScanEventOutPaginated]:
    """
    Fetch many scan events with pagination and filters.

    Parameters:
        filter_params (ScanEventFilters): Filter parameters.
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        ScanEventOutPaginated: The list of scan events with pagination data.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    filters = filter_params.model_dump(exclude_none=True)
    events, total = scan_event_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        filters=filters
    )
    pages = (total + size - 1) // size
    return {
        "items": events,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/by-ean/{ean}", response_model=List[Optional[ScanEventOut]], status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def fetch_scan_events_by_ean(
    ean: str,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db)
) -> List[Optional[ScanEventOut]]:
    """
    Fetch scan events by EAN.

    Parameters:
        ean (str): The EAN of the product.
        limit (int): Maximum number of results to return (default 100, max 1000).
        db (Session): The database session.

    Returns:
        List[Optional[ScanEventOut]]: The list of scan events for the given EAN.
    """
    return scan_event_crud.get_by_ean(db, ean, limit)


@router.get(
    "/{id}",
    response_model=Optional[ScanEventOut],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def fetch_scan_event_by_id(
    id: int, db: Session = Depends(get_db)
) -> ScanEventOut:
    """
    Fetches a scan event by its ID.

    Parameters:
        id (int): The ID of the scan event.
        db (Session): The database session.

    Returns:
        ScanEventOut: The fetched scan event.

    Raises:
        HTTPException: If the scan event is not found.
    """
    event = scan_event_crud.get_one(db, ScanEvent.id == id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan event with id {id} not found",
        )
    return event


@router.post(
    "/",
    response_model=ScanEventOut,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
    response_model_exclude_unset=True,
)
async def create_scan_event(
    event_create: Annotated[
        ScanEventCreate,
        Body(
            examples=[
                {
                    "ean": "1234567890123",
                    "latitude": 48.8566,
                    "longitude": 2.3522,
                    "shop_id": 1,
                    "lookup_api_response": '{"status": "success"}',
                    "user_id": 1
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
    current_user_or_client: User | ApiClient = Depends(
        get_current_active_user_or_client),
):
    """
    Create a scan event.

    If latitude/longitude are provided and no shop_id is set :
    1. Check if a shop exists within 100 meters
    2. If not, query OpenStreetMap for nearby shops (also 100 meters)
    3. Create the shop in the database if found
    4. Link the scan event to the shop

    Note that if OSM api times out or fail, the scan event will still be created without shop

    Parameters:
        event_create (ScanEventCreate): The scan event data to be created.
        db (Session): The database session.
        current_user_or_client (User | ApiClient): The current active user or API client.

    Returns:
        ScanEventOut: The created scan event.

    Raises:
        HTTPException: If the user does not exist.
        HTTPException: If there is an error creating the scan event.
    """
    # Find or create a shop (and collect nearby shops for the response)
    nearby_shops = []
    if event_create.latitude and event_create.longitude and not event_create.shop_id:
        # Check if shop exists within 100 meters in our DB
        existing_shop = shop_crud.find_nearby(
            db,
            event_create.latitude,
            event_create.longitude,
            radius_meters=100
        )

        if existing_shop:
            event_create.shop_id = existing_shop.id
            # Collect all other nearby shops from our DB for alternatives
            all_nearby = shop_crud.find_all_nearby(
                db,
                event_create.latitude,
                event_create.longitude,
                radius_meters=100
            )
            nearby_shops = [s for s in all_nearby if s.id != existing_shop.id]
        else:
            # Query OpenStreetMap for ALL nearby shops
            osm_shops_data = await osm_service.find_nearby_shops(
                event_create.latitude,
                event_create.longitude,
                radius_meters=100
            )

            if osm_shops_data:
                # Store the full OSM API response
                event_create.lookup_api_response = json.dumps(osm_shops_data)

                # Return OSM shops as-is (not created in DB yet).
                # The closest one is linked only if it already exists in our DB.
                for osm_shop_data in osm_shops_data:
                    existing_osm_shop = shop_crud.get_by_osm_id(
                        db, osm_shop_data["osm_id"])
                    if existing_osm_shop:
                        nearby_shops.append(existing_osm_shop)
                    else:
                        # Return OSM data without creating in DB — shop will be
                        # created only when the user confirms via confirm-shop endpoint
                        nearby_shops.append(osm_shop_data)

                # Link the closest shop if it already exists in our DB
                if nearby_shops and isinstance(nearby_shops[0], dict) is False:
                    event_create.shop_id = nearby_shops[0].id

    try:
        event = scan_event_crud.create(db, event_create)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "foreign key constraint" in error_message.lower() and "user_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with id {event_create.user_id} does not exist",
            ) from e
        elif "foreign key constraint" in error_message.lower() and "shop_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Shop with id {event_create.shop_id} does not exist",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create scan event. Error: {str(e)}",
        ) from e

    # Award XP for the scan. /scan-events/ is only ever called for
    # Vegandex products (plain scans go through POST /users/me/scans
    # instead), so every successful create here is a vegandex_scan — no
    # "is this product in the vegandex" check needed. Only if the event
    # is tied to a real user (API-client-only scans with no user_id
    # don't earn anything).
    xp_grants = []
    scan_user = None
    if event.user_id:
        scan_user = user_crud.get_one(db, User.id == event.user_id)
        if scan_user:
            vegandex_xp = award_xp(
                db, scan_user, XPAction.VEGANDEX_SCAN,
                reference_type="scan_event", reference_id=event.id,
            )
            if vegandex_xp:
                xp_grants.append(XPGrant(
                    action_key=XPAction.VEGANDEX_SCAN, xp=vegandex_xp))

            # Only resolvable here if the shop was already known (nearby
            # DB match or a single unambiguous OSM hit). When it needs
            # user disambiguation, shop_id is still None at this point —
            # confirm_shop() evaluates the bonus once it gets set.
            first_in_shop_grant = _award_first_in_shop_bonus(
                db, event, scan_user)
            if first_in_shop_grant:
                xp_grants.append(first_in_shop_grant)

    # Build response with nearby shops (excluding the one already linked)
    response = ScanEventOut.model_validate(event)
    response.xp_grants = xp_grants
    response.xp_awarded = sum(grant.xp for grant in xp_grants)
    response.level = scan_user.level if scan_user else None
    if nearby_shops:
        result = []
        for shop in nearby_shops:
            if isinstance(shop, dict):
                # OSM-only shop (not yet in DB)
                result.append(NearbyShopOut(
                    name=shop.get("name"),
                    address=shop.get("address"),
                    city=shop.get("city"),
                    osm_id=shop.get("osm_id"),
                    latitude=shop.get("latitude"),
                    longitude=shop.get("longitude"),
                ))
            elif shop.id != event.shop_id:
                # DB shop (exclude the one already linked)
                result.append(NearbyShopOut(
                    id=shop.id,
                    name=shop.name,
                    address=shop.address,
                    city=shop.city,
                    osm_id=shop.osm_id,
                ))
        response.nearby_shops = result

        # If no shop was linked yet, set shop_name from the closest nearby shop
        # so the old app can still ask "Are you in [shop_name]?"
        if not response.shop_name and nearby_shops:
            first = nearby_shops[0]
            response.shop_name = first.get("name") if isinstance(
                first, dict) else first.name
    return response


@router.put(
    "/{id}",
    response_model=ScanEventOut,
    status_code=status.HTTP_200_OK,
)
def update_scan_event(
    id: int,
    event_update: ScanEventUpdate,
    db: Session = Depends(get_db),
    current_user_or_client: User | ApiClient = Depends(
        get_current_active_user_or_client),
):
    """
    Update a scan event by its ID.
    Only admins can update scan events.

    Parameters:
        id (int): The ID of the scan event to be updated.
        event_update (ScanEventUpdate): The updated scan event data.
        db (Session): The database session.
        current_user_or_client (User | ApiClient): The current active user or API client.

    Returns:
        ScanEventOut: The updated scan event.

    Raises:
        HTTPException: If the scan event does not exist.
        HTTPException: If there is an error updating the scan event.
    """
    event = scan_event_crud.get_one(db, ScanEvent.id == id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan event with id {id} not found",
        )

    try:
        event = scan_event_crud.update(db, event, event_update)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "foreign key constraint" in error_message.lower() and "user_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with id {event_update.user_id} does not exist",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update scan event with id {id}. Error: {str(e)}",
        ) from e
    return event


@router.post(
    "/{id}/confirm-shop",
    response_model=ScanEventOut,
    status_code=status.HTTP_200_OK,
)
def confirm_shop(
    id: int,
    body: ConfirmShopRequest,
    db: Session = Depends(get_db),
    current_user_or_client: User | ApiClient = Depends(
        get_current_active_user_or_client),
):
    """
    Confirm which shop the user is in by osm_id.

    Looks up the OSM shop data from the scan event's stored lookup_api_response,
    creates the shop in DB if it doesn't exist, and links it to the scan event.

    Path parameter:
        id: The scan event ID (e.g. /scan-events/53/confirm-shop)

    Example body:
        { "osm_id": "398056954" }
    """
    event = scan_event_crud.get_one(db, ScanEvent.id == id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan event with id {id} not found",
        )

    # Captured before resolving the shop: the first-in-shop bonus only
    # applies the first time this event's shop_id becomes known, not on
    # a re-confirmation of an already-linked event.
    had_shop_before = event.shop_id is not None

    # Check if this shop already exists in DB
    existing_shop = shop_crud.get_by_osm_id(db, body.osm_id)
    if existing_shop:
        event = scan_event_crud.update(
            db, event, ScanEventUpdate(shop_id=existing_shop.id))
    else:
        # Find the OSM data from the stored lookup response
        if not event.lookup_api_response:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No OSM lookup data stored for this scan event",
            )

        osm_shops_data = json.loads(event.lookup_api_response)
        osm_shop_data = next(
            (s for s in osm_shops_data if s.get("osm_id") == body.osm_id), None)

        if osm_shop_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Shop with osm_id {body.osm_id} not found in lookup response",
            )

        # Create the shop in DB
        try:
            new_shop = shop_crud.create(db, ShopCreate(**osm_shop_data))
        except IntegrityError:
            db.rollback()
            # Race condition — another request created it
            new_shop = shop_crud.get_by_osm_id(db, body.osm_id)
            if new_shop is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create shop",
                )

        event = scan_event_crud.update(
            db, event, ScanEventUpdate(shop_id=new_shop.id))

    response = ScanEventOut.model_validate(event)
    if not had_shop_before and event.user_id:
        scan_user = user_crud.get_one(db, User.id == event.user_id)
        if scan_user:
            grant = _award_first_in_shop_bonus(db, event, scan_user)
            if grant:
                response.xp_grants = [grant]
                response.xp_awarded = grant.xp
                response.level = scan_user.level
    return response


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["admin"]))])
def delete_scan_event(
    id: int,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
):
    """
    Deletes a scan event by its ID.
    Only admins can delete scan events.

    Parameters:
        id (int): The ID of the scan event to delete.
        db (Session): The database session.
        active_user (User): The current active user.

    Raises:
        HTTPException: If the scan event is not found.
        HTTPException: If there is an error while deleting the scan event.
    """
    event = scan_event_crud.get_one(db, ScanEvent.id == id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan event with id {id} not found. Cannot delete.",
        )
    try:
        scan_event_crud.delete(db, event)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete scan event with id {id}. Error: {str(e)}",
        ) from e
