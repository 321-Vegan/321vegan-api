from fastapi import APIRouter, Depends, HTTPException, status as apiStatus
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from typing import Optional
import sqlite3
import tempfile
import os

from app.database.db import get_db
from app.models.product import Product, ProductState, ProductStatus
from app.models.brand import Brand
from app.models.cosmetic import Cosmetic
from app.models.additive import Additive, AdditiveStatus
from app.models.household_cleaner import HouseholdCleaner
from app.routes.dependencies import get_current_user
from app.models.user import User
from app.log import get_logger

router = APIRouter()
log = get_logger(__name__)


def map_status_to_export_format(status: ProductStatus) -> str:
    """Map internal ProductStatus to export format."""
    mapping = {
        ProductStatus.VEGAN: "V",
        ProductStatus.NON_VEGAN: "R",
        ProductStatus.MAYBE_VEGAN: "M",
        ProductStatus.NOT_FOUND: "N"
    }
    return mapping.get(status, "N")


def extract_brand_name(product: Product) -> Optional[str]:
    """Extract brand name from product - either from brand relationship or description."""
    if product.brand:
        return ','.join(filter(None, [product.brand.name, product.brand.parent_name]))
    elif product.description:
        return product.description.strip()
    return None


def export_brands_to_sqlite(db: Session, sqlite_cursor: sqlite3.Cursor) -> dict:
    """Export all brands to SQLite brands table."""
    # Query all brands from the database
    brands_to_export = db.query(Brand).all()

    if not brands_to_export:
        return {"exported": 0, "skipped": 0}

    exported_count = 0
    skipped_count = 0

    # Clear existing brands data
    sqlite_cursor.execute("DELETE FROM brands")

    for brand in brands_to_export:
        try:
            sqlite_cursor.execute('''
                INSERT OR REPLACE INTO brands 
                (id, name, parent_id, boycott) 
                VALUES (?, ?, ?, ?)
            ''', (
                brand.id,
                brand.name,
                brand.parent_id,
                brand.boycott
            ))
            exported_count += 1
        except Exception as e:
            log.error(f"Error inserting brand {brand.id} ({brand.name}): {e}")
            skipped_count += 1

    return {"exported": exported_count, "skipped": skipped_count}


def create_sqlite_database(db_path: str) -> sqlite3.Connection:
    """Create SQLite database with the required table structure."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the brands table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id INTEGER,
            boycott BOOLEAN DEFAULT 0,
            FOREIGN KEY (parent_id) REFERENCES brands (id)
        )
    ''')

    # Create the products table with the updated schema
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            code TEXT PRIMARY KEY,
            name TEXT,
            brand_id INTEGER,
            brand TEXT,
            status TEXT,
            biodynamie TEXT,
            problem TEXT,
            has_non_vegan_old_receipe BOOLEAN DEFAULT 0,
            FOREIGN KEY (brand_id) REFERENCES brands (id)
        )
    ''')

    conn.commit()
    return conn


def create_cosmetics_sqlite_database(db_path: str) -> sqlite3.Connection:
    """Create SQLite database with the required table structure for cosmetics."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the cosmetics table with the required schema
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cosmetics (
            brand TEXT PRIMARY KEY,
            vegan TEXT,
            cf TEXT
        )
    ''')

    conn.commit()
    return conn


def create_household_cleaners_sqlite_database(db_path: str) -> sqlite3.Connection:
    """Create SQLite database with the required table structure for household cleaners."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the household cleaners table with the required schema
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS household_cleaners (
            brand TEXT PRIMARY KEY,
            vegan TEXT,
            cf TEXT
        )
    ''')

    conn.commit()
    return conn


def create_additives_sqlite_database(db_path: str) -> sqlite3.Connection:
    """Create SQLite database with the required table structure for additives."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the additives table with the required schema
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS additives (
            e_number TEXT PRIMARY KEY,
            name TEXT,
            state TEXT,
            description TEXT
        )
    ''')

    conn.commit()
    return conn


@router.get("/products/sqlite", summary="Export products to SQLite")
async def export_products_to_sqlite(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export published products to SQLite format.

    Returns a downloadable SQLite file containing:

    Brands table with columns:
    - id: brand ID
    - name: brand name  
    - parent_id: parent brand ID (if exists)
    - boycott: boycott status (0 or 1)

    Products table with columns:
    - code: barcode (ean)
    - name: product name (trimmed)
    - brand_id: brand ID (if product has a brand)
    - brand: product description (if product has no brand_id)
    - status: V (vegan), R (not vegan), M (maybe vegan), N (not found)
    - biodynamie: Y or null
    - problem: problem_description for non-vegan products
    """

    try:
        # Create temporary SQLite file
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.db', prefix='vegan_products_')
        os.close(temp_fd)

        # Create SQLite database
        sqlite_conn = create_sqlite_database(temp_path)
        sqlite_cursor = sqlite_conn.cursor()

        # Clear existing data
        sqlite_cursor.execute("DELETE FROM products")

        # Query published products with their brands.
        # Only these states are exported - TO_INVESTIGATE (and other
        # in-progress states) are intentionally excluded.
        published_products = db.query(Product).filter(
            Product.state.in_([
                ProductState.PUBLISHED,
                ProductState.NEED_CONTACT,
                ProductState.WAITING_REPLY
            ])
        ).all()

        # Export brands first
        brand_stats = export_brands_to_sqlite(db, sqlite_cursor)
        log.info(
            f"Brands export: {brand_stats['exported']} exported, {brand_stats['skipped']} skipped")

        exported_count = 0
        skipped_count = 0

        for product in published_products:
            # Prepare data for export
            code = product.ean.strip()
            name = product.name.strip() if product.name else None

            # Handle brand logic: use brand_id if available, otherwise use description as brand
            brand_id = product.brand_id if product.brand_id else None
            brand = None
            if not product.brand_id and product.description:
                brand = product.description.strip()

            status = map_status_to_export_format(product.status)
            biodynamie = "Y" if product.biodynamic else None
            problem = product.problem_description if product.status == ProductStatus.NON_VEGAN else None

            has_non_vegan_old_receipe = product.has_non_vegan_old_receipe if product.has_non_vegan_old_receipe else False

            # Insert into SQLite
            try:
                sqlite_cursor.execute('''
                    INSERT OR REPLACE INTO products 
                    (code, name, brand_id, brand, status, biodynamie, problem, has_non_vegan_old_receipe) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (code, name, brand_id, brand, status, biodynamie, problem, has_non_vegan_old_receipe))

                exported_count += 1

            except Exception as e:
                log.error(f"Error inserting product {code}: {e}")
                skipped_count += 1

        # Commit changes
        sqlite_conn.commit()
        sqlite_conn.close()

        return FileResponse(
            path=temp_path,
            filename="vegan_products.db",
            media_type="application/octet-stream",
            background=BackgroundTask(os.unlink, temp_path)
        )

    except Exception as e:
        log.error(f"Error during SQLite export: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export to SQLite: {str(e)}"
        )


@router.get("/products/sqlite/stats", summary="Get products SQLite export statistics")
async def get_export_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about products that would be exported to SQLite.
    """

    try:
        # Query published products - matches the export filter above.
        # TO_INVESTIGATE products are intentionally not exported.
        published_products = db.query(Product).filter(
            Product.state.in_([
                ProductState.PUBLISHED,
                ProductState.NEED_CONTACT,
                ProductState.WAITING_REPLY
            ])
        ).all()

        # Calculate statistics
        total_products = len(published_products)
        products_with_ean = len(
            [p for p in published_products if p.ean and p.ean.strip()])

        # Brand statistics
        products_with_brand_id = len(
            [p for p in published_products if p.ean and p.ean.strip() and p.brand_id])
        products_with_description_as_brand = len(
            [p for p in published_products if p.ean and p.ean.strip() and not p.brand_id and p.description])
        unique_brand_ids = set(
            p.brand_id for p in published_products if p.brand_id)

        status_counts = {}
        biodynamic_count = 0
        problems_count = 0

        for product in published_products:
            if not product.ean or not product.ean.strip():
                continue

            # Count by status
            status_key = map_status_to_export_format(product.status)
            status_counts[status_key] = status_counts.get(status_key, 0) + 1

            # Count biodynamic
            if product.biodynamic:
                biodynamic_count += 1

            # Count problems
            if product.status == ProductStatus.NON_VEGAN and product.problem_description:
                problems_count += 1

        return {
            "total_products": total_products,
            "exportable_products": products_with_ean,
            "skipped_products": total_products - products_with_ean,
            "included_states": ["PUBLISHED", "NEED_CONTACT", "WAITING_REPLY"],
            "brand_statistics": {
                "unique_brands_in_export": len(unique_brand_ids),
                "products_with_brand_id": products_with_brand_id,
                "products_with_description_as_brand": products_with_description_as_brand,
                "products_without_brand_info": products_with_ean - products_with_brand_id - products_with_description_as_brand
            },
            "status_distribution": {
                "vegan": status_counts.get("V", 0),
                "not_vegan": status_counts.get("R", 0),
                "maybe_vegan": status_counts.get("M", 0),
                "not_found": status_counts.get("N", 0)
            },
            "biodynamic_products": biodynamic_count,
            "products_with_problems": problems_count
        }

    except Exception as e:
        log.error(f"Error getting export statistics: {e}")
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get export statistics: {str(e)}"
        )


@router.get("/cosmetics/sqlite", summary="Export cosmetics to SQLite")
async def export_cosmetics_to_sqlite(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export all cosmetics to SQLite format.

    Returns a downloadable SQLite file containing cosmetics with columns:
    - brand: brand name
    - vegan: Y (vegan) or N (not vegan)  
    - cf: Y (cruelty free) or N (not cruelty free)
    """

    try:
        # Temp SQL file
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.db', prefix='cosmetics_')
        os.close(temp_fd)

        # Create SQLite database
        sqlite_conn = create_cosmetics_sqlite_database(temp_path)
        sqlite_cursor = sqlite_conn.cursor()

        # Clear existing data
        sqlite_cursor.execute("DELETE FROM cosmetics")

        # Query all cosmetics
        all_cosmetics = db.query(Cosmetic).all()

        log.info(f"Found {len(all_cosmetics)} cosmetics for export")

        exported_count = 0
        skipped_count = 0

        for cosmetic in all_cosmetics:
            # Prepare data for export
            brand = cosmetic.brand_name.strip()
            vegan = "Y" if cosmetic.is_vegan else "N"
            cf = "Y" if cosmetic.is_cruelty_free else "N"

            # Insert into SQLite
            try:
                sqlite_cursor.execute('''
                    INSERT OR REPLACE INTO cosmetics 
                    (brand, vegan, cf) 
                    VALUES (?, ?, ?)
                ''', (brand, vegan, cf))

                exported_count += 1

            except Exception as e:
                log.error(f"Error inserting cosmetic {brand}: {e}")
                skipped_count += 1

        # Commit changes
        sqlite_conn.commit()
        sqlite_conn.close()

        log.info(
            f"Cosmetics export completed: {exported_count} exported, {skipped_count} skipped")

        return FileResponse(
            path=temp_path,
            filename="vegan_cosmetics.db",
            media_type="application/octet-stream",
            background=BackgroundTask(os.unlink, temp_path)
        )

    except Exception as e:
        log.error(f"Error during cosmetics SQLite export: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export cosmetics to SQLite: {str(e)}"
        )


@router.get("/cosmetics/sqlite/stats", summary="Get cosmetics SQLite export statistics")
async def get_cosmetics_export_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about cosmetics that would be exported to SQLite.
    """

    try:
        # Query all cosmetics
        all_cosmetics = db.query(Cosmetic).all()

        # Calculate statistics
        total_cosmetics = len(all_cosmetics)
        cosmetics_with_brand = len(
            [c for c in all_cosmetics if c.brand_name and c.brand_name.strip()])

        vegan_count = 0
        cruelty_free_count = 0
        both_vegan_and_cf = 0

        for cosmetic in all_cosmetics:
            if not cosmetic.brand_name or not cosmetic.brand_name.strip():
                continue

            if cosmetic.is_vegan:
                vegan_count += 1
            if cosmetic.is_cruelty_free:
                cruelty_free_count += 1
            if cosmetic.is_vegan and cosmetic.is_cruelty_free:
                both_vegan_and_cf += 1
                vegan_count -= 1
                cruelty_free_count -= 1

        return {
            "total_cosmetics": total_cosmetics,
            "exportable_cosmetics": cosmetics_with_brand,
            "skipped_cosmetics": total_cosmetics - cosmetics_with_brand,
            "vegan_cosmetics": vegan_count,
            "cruelty_free_cosmetics": cruelty_free_count,
            "both_vegan_and_cruelty_free": both_vegan_and_cf,
            "statistics": {
                "vegan_percentage": round((vegan_count / cosmetics_with_brand * 100), 2) if cosmetics_with_brand > 0 else 0,
                "cruelty_free_percentage": round((cruelty_free_count / cosmetics_with_brand * 100), 2) if cosmetics_with_brand > 0 else 0
            }
        }

    except Exception as e:
        log.error(f"Error getting cosmetics export statistics: {e}")
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cosmetics export statistics: {str(e)}"
        )


@router.get("/additives/sqlite", summary="Export additives to SQLite")
async def export_additives_to_sqlite(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export all additives to SQLite format.

    Returns a downloadable SQLite file containing additives with columns:
    - e_number: e number
    - name: name
    - state: 'vegan', 'carniste' or 'Ça dépend'
    - description: text explaining why the additive is not vegan
    """

    try:
        # Temp SQL file
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.db', prefix='additives_')
        os.close(temp_fd)

        # Create SQLite database
        sqlite_conn = create_additives_sqlite_database(temp_path)
        sqlite_cursor = sqlite_conn.cursor()

        # Clear existing data
        sqlite_cursor.execute("DELETE FROM additives")

        # Query all additives
        all_additives = db.query(Additive).all()

        log.info(f"Found {len(all_additives)} additives for export")

        exported_count = 0
        skipped_count = 0

        for additive in all_additives:
            # Prepare data for export
            e_number = additive.e_number.strip()
            name = additive.name.strip()
            description = additive.description.strip()
            state = "carniste" if additive.status == AdditiveStatus.NON_VEGAN else "vegan" if additive.status == AdditiveStatus.VEGAN else "Ça dépend"

            # Insert into SQLite
            try:
                sqlite_cursor.execute('''
                    INSERT OR REPLACE INTO additives 
                    (e_number, name, state, description) 
                    VALUES (?, ?, ?, ?)
                ''', (e_number, name, state, description))

                exported_count += 1

            except Exception as e:
                log.error(f"Error inserting additive {e_number}: {e}")
                skipped_count += 1

        # Commit changes
        sqlite_conn.commit()
        sqlite_conn.close()

        log.info(
            f"Additives export completed: {exported_count} exported, {skipped_count} skipped")

        return FileResponse(
            path=temp_path,
            filename="vegan_additives.db",
            media_type="application/octet-stream",
            background=BackgroundTask(os.unlink, temp_path)
        )

    except Exception as e:
        log.error(f"Error during additives SQLite export: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export additives to SQLite: {str(e)}"
        )


@router.get("/additives/sqlite/stats", summary="Get additives SQLite export statistics")
async def get_additives_export_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about additives that would be exported to SQLite.
    """

    try:
        # Query all additives
        all_additives = db.query(Additive).all()

        # Calculate statistics
        total_additives = len(all_additives)

        vegan_count = 0
        maybe_vegan_count = 0
        non_vegan_count = 0

        for additive in all_additives:
            if additive.status == AdditiveStatus.VEGAN:
                vegan_count += 1
            elif additive.status == AdditiveStatus.MAYBE_VEGAN:
                maybe_vegan_count += 1
            else:
                non_vegan_count += 1

        return {
            "total_additives": total_additives,
            "vegan_additives": vegan_count,
            "maybe_vegan_additives": maybe_vegan_count,
            "non_vegan_additives": non_vegan_count,
        }

    except Exception as e:
        log.error(f"Error getting additives export statistics: {e}")
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get additives export statistics: {str(e)}"
        )


@router.get("/household-cleaners/sqlite", summary="Export household cleaners to SQLite")
async def export_household_cleaners_to_sqlite(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export all household cleaners to SQLite format.

    Returns a downloadable SQLite file containing household cleaners with columns:
    - brand: brand name
    - vegan: Y (vegan) or N (not vegan)  
    - cf: Y (cruelty free) or N (not cruelty free)
    """

    try:
        # Temp SQL file
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.db', prefix='household_cleaners_')
        os.close(temp_fd)

        # Create SQLite database
        sqlite_conn = create_household_cleaners_sqlite_database(temp_path)
        sqlite_cursor = sqlite_conn.cursor()

        # Clear existing data
        sqlite_cursor.execute("DELETE FROM household_cleaners")

        # Query all household cleaners
        all_household_cleaners = db.query(HouseholdCleaner).all()

        log.info(
            f"Found {len(all_household_cleaners)} household cleaners for export")

        exported_count = 0
        skipped_count = 0

        for household_cleaner in all_household_cleaners:
            # Prepare data for export
            brand = household_cleaner.brand_name.strip()
            vegan = "Y" if household_cleaner.is_vegan else "N"
            cf = "Y" if household_cleaner.is_cruelty_free else "N"

            # Insert into SQLite
            try:
                sqlite_cursor.execute('''
                    INSERT OR REPLACE INTO household_cleaners 
                    (brand, vegan, cf) 
                    VALUES (?, ?, ?)
                ''', (brand, vegan, cf))

                exported_count += 1

            except Exception as e:
                log.error(f"Error inserting household cleaner {brand}: {e}")
                skipped_count += 1

        # Commit changes
        sqlite_conn.commit()
        sqlite_conn.close()

        log.info(
            f"Household cleaners export completed: {exported_count} exported, {skipped_count} skipped")

        return FileResponse(
            path=temp_path,
            filename="vegan_household_cleaners.db",
            media_type="application/octet-stream",
            background=BackgroundTask(os.unlink, temp_path)
        )

    except Exception as e:
        log.error(f"Error during household cleaners SQLite export: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export household cleaners to SQLite: {str(e)}"
        )


@router.get("/household-cleaners/sqlite/stats", summary="Get household cleaners SQLite export statistics")
async def get_household_cleaners_export_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about household cleaners that would be exported to SQLite.
    """

    try:
        # Query all household_cleaners
        all_household_cleaners = db.query(HouseholdCleaner).all()

        # Calculate statistics
        total_household_cleaners = len(all_household_cleaners)

        vegan_count = 0
        cruelty_free_count = 0
        both_vegan_and_cf = 0

        for household_cleaner in all_household_cleaners:
            if household_cleaner.is_vegan:
                vegan_count += 1
            if household_cleaner.is_cruelty_free:
                cruelty_free_count += 1
            if household_cleaner.is_vegan and household_cleaner.is_cruelty_free:
                both_vegan_and_cf += 1
                vegan_count -= 1
                cruelty_free_count -= 1

        return {
            "total_household_cleaners": total_household_cleaners,
            "vegan_household_cleaners": vegan_count,
            "cruelty_free_household_cleaners": cruelty_free_count,
            "both_vegan_and_cruelty_free": both_vegan_and_cf,
        }

    except Exception as e:
        log.error(f"Error getting household cleaners export statistics: {e}")
        raise HTTPException(
            status_code=apiStatus.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get household cleaners export statistics: {str(e)}"
        )
