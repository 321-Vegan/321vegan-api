import re
import unicodedata
import uuid
from pathlib import PurePosixPath
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.crud.veganuary_week import veganuary_week_crud
from app.database.db import get_db
from app.log import get_logger
from app.models.veganuary_week import VeganuaryWeek
from app.routes.dependencies import RoleChecker, get_admin_or_client
from app.schemas.veganuary_week import (
    VeganuaryImageOut,
    VeganuaryVersionOut,
    VeganuaryWeekIn,
    VeganuaryWeekOut,
)
from app.services.s3_file_manager import s3_file_manager

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_or_client)])


@router.get("/", response_model=List[VeganuaryWeekOut], status_code=status.HTTP_200_OK)
def fetch_veganuary_weeks(db: Session = Depends(get_db)) -> List[VeganuaryWeek]:
    """
    Fetch every week of the Veganuary course, in order.

    Returns:
        List[VeganuaryWeekOut]: Each week's number, last change and JSON.
    """
    return veganuary_week_crud.get_all_ordered(db)


@router.get("/version", response_model=VeganuaryVersionOut, status_code=status.HTTP_200_OK)
def fetch_veganuary_version(db: Session = Depends(get_db)) -> VeganuaryVersionOut:
    """
    Fetch the version of the course: the app downloads the weeks again only
    when it changes. Null while no week is stored (the app keeps its own).
    """
    return VeganuaryVersionOut(version=veganuary_week_crud.version(db))


# The course's images, in the bucket: the weeks' JSON refers to them by
# their path ("veganuary/cover-l-amorce_1a2b3c4d.webp")
IMAGES_PREFIX = "veganuary/"


def _slug(name: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60] or "image"


@router.get(
    "/images",
    response_model=List[VeganuaryImageOut],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def fetch_veganuary_images() -> List[VeganuaryImageOut]:
    """
    List the course's images in the bucket, newest first.

    Returns:
        List[VeganuaryImageOut]: Each image's path, to write in a week's JSON.
    """
    images = []
    paginator = s3_file_manager.s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=s3_file_manager.bucket_name, Prefix=IMAGES_PREFIX
    ):
        for item in page.get("Contents", []):
            images.append(
                VeganuaryImageOut(
                    path=item["Key"],
                    size=item["Size"],
                    updated_at=item["LastModified"],
                )
            )
    return sorted(images, key=lambda image: image.updated_at, reverse=True)


@router.post(
    "/images",
    response_model=VeganuaryImageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def upload_veganuary_image(
    file: UploadFile = File(..., description="Image (JPG, PNG, WebP max 5MB)"),
) -> VeganuaryImageOut:
    """
    Add an image for the course, stored as WebP under veganuary/. Its path
    is new on each upload (the apps keep images for good): to replace an
    image, upload the new one and change its path in the JSON.

    Returns:
        VeganuaryImageOut: The path to write in a week's JSON.
    """
    name = _slug(PurePosixPath(file.filename or "").stem)
    path = s3_file_manager.upload_image(
        f"{IMAGES_PREFIX}{name}_{uuid.uuid4().hex[:8]}", file
    )
    return VeganuaryImageOut(path=path)


@router.put(
    "/{number}",
    response_model=VeganuaryWeekOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def put_veganuary_week(
    number: int, week_in: VeganuaryWeekIn, db: Session = Depends(get_db)
) -> VeganuaryWeek:
    """
    Create or replace a week of the course.

    Only a quick check is made here: the admin tool checks the whole week
    as the app reads it (321vegan-tool, validateWeek.js) before sending it.

    Raises:
        HTTPException: If the JSON's number isn't the one of the URL, or it has no days.
    """
    content = week_in.content
    if content.get("number") != number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The JSON is for week {content.get('number')}, not {number}",
        )
    if not isinstance(content.get("days"), list) or not content["days"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A week needs its days",
        )
    try:
        return veganuary_week_crud.upsert(db, number, content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't save week {number}. Error: {str(e)}",
        ) from e


@router.delete(
    "/{number}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def delete_veganuary_week(number: int, db: Session = Depends(get_db)):
    """
    Remove a week: its days disappear from the app at its next visit.

    Raises:
        HTTPException: If the week isn't stored.
    """
    week = veganuary_week_crud.get_one(db, VeganuaryWeek.number == number)
    if week is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Veganuary week {number} not found",
        )
    veganuary_week_crud.delete(db, week)
