"""
One-off script: backfill address/city/country for shops missing them.

Uses OpenStreetMap Nominatim:
  - shops with an osm_id/osm_type: batched /lookup (up to 50 per request) -
    reads the same tags as the OSM object itself, most accurate.
  - shops without an osm_id: /reverse, one request per shop, from lat/lng.

Only fills fields that are currently empty; never overwrites existing data.
Respects Nominatim's usage policy (max ~1 request/second, identifying
User-Agent) - this is a one-off maintenance run, not meant to be scheduled.

Usage (from repo root, inside the API container):
    poetry run python -m scripts.backfill_shop_addresses            # dry run
    poetry run python -m scripts.backfill_shop_addresses --apply    # writes the changes
    poetry run python -m scripts.backfill_shop_addresses --limit 20 # test on a few shops
"""
import argparse
import time
from functools import partial
from typing import Dict, List, Optional

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.app.database.session import build_sqlalchemy_database_url_from_env
from src.app.database.db import get_ctx_db
from src.app.log import get_logger
from src.app.config import settings
from src.app.models import Shop

log = get_logger(__name__)

DATABASE_URL = build_sqlalchemy_database_url_from_env(settings)

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = f"321veganapi-backfill/1.0 ({settings.FROM_EMAIL})"
LOOKUP_BATCH_SIZE = 50
REQUEST_DELAY_SECONDS = 1.1
OSM_TYPE_PREFIX = {"node": "N", "way": "W", "relation": "R"}


def _is_missing(value: Optional[str]) -> bool:
    return value is None or value.strip() == ""


def _extract_address(addr: dict) -> dict:
    road = addr.get("road") or addr.get("pedestrian") or addr.get("path") or ""
    house_number = addr.get("house_number") or ""
    address = f"{house_number} {road}".strip() if house_number else road
    city = (
        addr.get("city") or addr.get("town") or addr.get("village")
        or addr.get("municipality") or ""
    )
    country = addr.get("country") or ""
    return {"address": address.strip(), "city": city, "country": country}


def _apply_fields(shop: Shop, found: dict) -> bool:
    """Fill only the fields that are currently empty. Returns True if anything changed."""
    changed = False
    for field in ("address", "city", "country"):
        if _is_missing(getattr(shop, field)) and found.get(field):
            setattr(shop, field, found[field])
            changed = True
    return changed


def _fetch_lookup(client: httpx.Client, shops: List[Shop]) -> Dict[str, dict]:
    """Batch-fetch address data for shops with an osm_id, keyed by e.g. 'N12345'."""
    osm_ids = [f"{OSM_TYPE_PREFIX[s.osm_type]}{s.osm_id}" for s in shops]
    response = client.get(
        f"{NOMINATIM_URL}/lookup",
        params={
            "osm_ids": ",".join(osm_ids),
            "format": "json",
            "addressdetails": 1,
            "accept-language": "fr",
        },
    )
    response.raise_for_status()
    results = {}
    for item in response.json():
        key = f"{item.get('osm_type', '')[:1].upper()}{item.get('osm_id')}"
        results[key] = _extract_address(item.get("address", {}))
    return results


def _fetch_reverse(client: httpx.Client, shop: Shop) -> Optional[dict]:
    response = client.get(
        f"{NOMINATIM_URL}/reverse",
        params={
            "lat": shop.latitude,
            "lon": shop.longitude,
            "format": "json",
            "addressdetails": 1,
            "accept-language": "fr",
        },
    )
    response.raise_for_status()
    data = response.json()
    if "address" not in data:
        return None
    return _extract_address(data["address"])


def backfill(db: Session, apply: bool, limit: Optional[int] = None) -> None:
    query = db.query(Shop).filter(
        Shop.date_deleted.is_(None),
        or_(
            Shop.address.is_(None), Shop.address == "",
            Shop.city.is_(None), Shop.city == "",
            Shop.country.is_(None), Shop.country == "",
        ),
    )
    if limit:
        query = query.limit(limit)
    shops = query.all()
    log.info("Found %d shops missing address data", len(shops))

    with_osm = [s for s in shops if s.osm_id and s.osm_type in OSM_TYPE_PREFIX]
    with_osm_ids = {s.id for s in with_osm}
    without_osm = [s for s in shops if s.id not in with_osm_ids]

    updated, skipped = 0, 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0) as client:
        # Batched lookup for shops with a known OSM object.
        for i in range(0, len(with_osm), LOOKUP_BATCH_SIZE):
            batch = with_osm[i:i + LOOKUP_BATCH_SIZE]
            try:
                results = _fetch_lookup(client, batch)
            except Exception as e:
                log.error("Lookup batch failed: %s", e)
                results = {}
            for shop in batch:
                key = f"{OSM_TYPE_PREFIX[shop.osm_type]}{shop.osm_id}"
                found = results.get(key)
                if found and _apply_fields(shop, found):
                    updated += 1
                    log.info("Filled shop #%d (%s) via OSM lookup", shop.id, shop.name)
                else:
                    skipped += 1
            time.sleep(REQUEST_DELAY_SECONDS)

        # One-by-one reverse geocoding for shops without a usable OSM object.
        for shop in without_osm:
            try:
                found = _fetch_reverse(client, shop)
            except Exception as e:
                log.error("Reverse geocode failed for shop #%d: %s", shop.id, e)
                found = None
            if found and _apply_fields(shop, found):
                updated += 1
                log.info("Filled shop #%d (%s) via reverse geocode", shop.id, shop.name)
            else:
                skipped += 1
            time.sleep(REQUEST_DELAY_SECONDS)

    log.info("Done: %d shops updated, %d skipped (no data found)", updated, skipped)

    if apply:
        db.commit()
        log.info("Changes committed.")
    else:
        db.rollback()
        log.info("Dry run: no changes were saved. Re-run with --apply to persist them.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write the changes (default: dry run)")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of shops processed (for testing)")
    args = parser.parse_args()

    get_db = partial(get_ctx_db, database_url=DATABASE_URL)
    with get_db() as session:
        backfill(session, apply=args.apply, limit=args.limit)


if __name__ == "__main__":
    main()
