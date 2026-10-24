import os
import boto3
from botocore.config import Config
from fastapi import UploadFile, HTTPException
from typing import TypeVar
from app.utils import validate_image
from app.config import settings

ORMModel = TypeVar("ORMModel")


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

        Args: 
            object_name (str): the key of the object
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
        try:
            # Upload the file to the S3 service, typed so browsers display it
            self.s3_client.upload_fileobj(
                file.file, self.bucket_name, object_name,
                ExtraArgs={'ACL': 'public-read', 'ContentType': file.content_type})
            return object_name
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error saving file: {str(e)}")
        finally:
            file.file.close()

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
