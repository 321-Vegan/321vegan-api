import os

from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.log import get_logger

log = get_logger(__name__)


class Settings(BaseSettings):
    """
    Creates and populates a settings object from .env variables
    for easier access to envrionment variables within the code.
    """
    model_config = SettingsConfigDict(
        env_file="./.env.example", env_file_encoding="utf-8", case_sensitive=True
    )
    ENV: str

    POSTGRES_HOST: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int

    DATABASE_URL: str

    # SQLAlchemy connection pool (see src/app/database/session.py)
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_TIMEOUT: int = 30

    PGADMIN_DEFAULT_EMAIL: str
    PGADMIN_DEFAULT_PASSWORD: str

    USER_ADMIN_EMAIL: EmailStr
    USER_ADMIN_PASSWORD: str
    USER_ADMIN_NICKNAME: str

    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int

    # Email settings for password reset
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    FROM_EMAIL: EmailStr
    RESET_TOKEN_EXPIRE_HOURS: int

    # Frontend URL for password reset links
    FRONTEND_URL: str

    # Sentry
    SENTRY_DSN: str = ""

    # Geoapify Places API (nearby shop lookup); lookup is skipped if empty
    GEOAPIFY_API_KEY: str = ""

    # In-app purchase - Apple App Store
    APPLE_BUNDLE_ID: str = ""
    APPLE_ISSUER_ID: str = ""
    APPLE_KEY_ID: str = ""
    APPLE_PRIVATE_KEY_PATH: str = ""
    APPLE_ROOT_CA_CERT_PATH: str = ""
    APPLE_APP_ID: int | None = None

    # In-app purchase - Google Play
    GOOGLE_PLAY_PACKAGE_NAME: str = ""
    GOOGLE_SERVICE_ACCOUNT_PATH: str = ""

    # S3 bucket settings
    S3_STORAGE_REGION: str
    S3_STORAGE_URL: str
    S3_STORAGE_ACCESS_KEY: str
    S3_STORAGE_SECRET_KEY: str
    S3_STORAGE_BUCKET_NAME: str


class ContainerDevSettings(Settings):
    model_config = SettingsConfigDict(
        env_file="./.env.dev", env_file_encoding="utf-8", case_sensitive=True
    )
    ENV: str = "dev"


class ContainerTestSettings(Settings):
    model_config = SettingsConfigDict(
        env_file="./.env.test", env_file_encoding="utf-8", case_sensitive=True
    )
    ENV: str = "test"


class LocalTestSettings(Settings):
    model_config = SettingsConfigDict(
        env_file="./.env.test.local", env_file_encoding="utf-8", case_sensitive=True
    )
    ENV: str = "test"


class LocalDevSettings(Settings):
    model_config = SettingsConfigDict(
        env_file="./.env", env_file_encoding="utf-8", case_sensitive=True
    )
    ENV: str = "local"


def get_settings(env: str = "dev") -> Settings:
    """
    Return the settings object based on the environment.

    Parameters:
        env (str): The environment to retrieve the settings for. Defaults to "dev".

    Returns:
        Settings: The settings object based on the environment.

    Raises:
        ValueError: If the environment is invalid.
    """
    log.debug("getting settings for env: %s", env)

    if env.lower() in ["dev", "d", "development"]:
        return ContainerDevSettings()
    if env.lower() in ["test", "t", "testing"]:
        return ContainerTestSettings()
    if env.lower() in ["local", "l"]:
        return LocalDevSettings()

    raise ValueError("Invalid environment. Must be 'dev' or 'test' ,'local'.")


_env = os.environ.get("ENV", "local")

settings = get_settings(env=_env)
