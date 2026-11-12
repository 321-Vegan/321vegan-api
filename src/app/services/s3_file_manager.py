import os
import boto3
from io import BytesIO
from pathlib import PurePosixPath
from botocore.config import Config
from fastapi import UploadFile, HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from typing import TypeVar
from app.utils import validate_image
from app.config import settings

ORMModel = TypeVar("ORMModel")

# The app already sends photos at 1600px max: this only bounds other uploads,
# while keeping tall screenshots (brand answers) readable.
MAX_IMAGE_SIDE = 2048
WEBP_QUALITY = 80


class S3FileManager:
    def __init__(self, bucket_name: str = settings.S3_STORAGE_BUCKET_NAME):
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            "s3",
            region_name=settings.S3_STORAGE_REGION,
            endpoint_url=settings.S3_STORAGE_URL,
            aws_access_key_id=settings.S3_STORAGE_ACCESS_KEY,
            aws_secret_access_key=settings.S3_STORAGE_SECRET_KEY,
            config=Config(
                s3={'adressing_style': 'path'}
            )
        )

    def upload_image(self, object_name: str, file: UploadFile) -> str:
        """
        Upload any image in JPG, PNG or WebP format and Maximum size: 5MB to the S3 bucket.
        The image is stored as WebP, upright, at most MAX_IMAGE_SIDE px and
        without its metadata (EXIF, GPS).

        Args:
            object_name (str): the key of the object, its extension is replaced by .webp
            file (UploadFile): the Uploaded file

        Returns:
            str: S3 bucket path of the saved file

        Raises:
            HTTPException: If the file is not valid
        """
        if not validate_image(file):
            raise HTTPException(
                status_code=400,
                detail="Unsupported file format. Use JPG, PNG or WebP."
            )

        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)

        if file_size > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="File is too large. Maximum size: 5MB."
            )
        object_name = str(PurePosixPath(object_name).with_suffix(".webp"))
        try:
            webp = self._to_webp(file)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
            file.file.close()
            raise HTTPException(
                status_code=400, detail="Invalid image file.") from e
        try:
            # Upload the file to the S3 service, typed so browsers display it.
            # Keys are unique per upload, so clients may cache them forever.
            self.s3_client.upload_fileobj(
                webp, self.bucket_name, object_name,
                ExtraArgs={'ACL': 'public-read', 'ContentType': 'image/webp',
                           'CacheControl': 'public, max-age=31536000, immutable'})
            return object_name
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error saving file: {str(e)}")
        finally:
            file.file.close()

    @staticmethod
    def _to_webp(file: UploadFile) -> BytesIO:
        """Re-encode an uploaded image as an upright, bounded, metadata-free WebP."""
        with Image.open(file.file) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert(
                    "RGBA" if image.has_transparency_data else "RGB")
            output = BytesIO()
            # No exif= argument: the metadata is dropped
            image.save(output, "WEBP", quality=WEBP_QUALITY)
        output.seek(0)
        return output

    def upload_file(self, object_name: str, file: UploadFile) -> str:
        """
        Upload a file to the S3 bucket.

        Args: 
            object_name (str): the key of the object
            file (UploadFile): the Uploaded file

        Returns:
            str: S3 bucket path of the saved file

        Raises:
            HTTPException: If the file is not valid
        """
        try:
            # Upload the file to the S3 service
            self.s3_client.upload_fileobj(
                file.file, self.bucket_name, object_name, ExtraArgs={'ACL': 'public-read'})
            return object_name
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error saving file: {str(e)}")
        finally:
            file.file.close()

    def file_exists(self, object_name: str) -> bool:
        """
        Checks whether a file is present in the bucket.

        Args:
            object_name (str): the key of the object

        Returns:
            boolean: True if successfully founded otherwise False
        """
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name, Key=object_name)
            return True
        except Exception:
            pass
        return False

    def delete_file(self, object_name: str) -> bool:
        """
        Delete an object by name from S3 bucket.

        Args:
            object_name (str): the full name of the object 

        Returns:
            boolean: True if successfully deleted otherwise False
        """
        try:
            if (self.file_exists(object_name)):
                self.s3_client.delete_object(
                    Bucket=self.bucket_name, Key=object_name)
            return True
        except Exception:
            pass
        return False


s3_file_manager = S3FileManager()
