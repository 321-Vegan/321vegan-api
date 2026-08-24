from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings, settings


def build_sqlalchemy_database_url_from_env(_settings: Settings) -> str:
    """
    Builds a SQLAlchemy URL based on the provided .env settings.

    Parameters:
        _settings (Settings): An instance of the Settings class 
        containing the PostgreSQL connection details.

    Returns:
        str: The generated SQLAlchemy URL.
    """
    return (
        f"postgresql://{_settings.POSTGRES_USER}:{_settings.POSTGRES_PASSWORD}"
        f"@{_settings.POSTGRES_HOST}:{_settings.POSTGRES_PORT}/{_settings.POSTGRES_DB}"
    )


def get_engine(
    database_url: str,
    echo=False,
    pool_size: int = settings.DB_POOL_SIZE,
    max_overflow: int = settings.DB_MAX_OVERFLOW,
    pool_timeout: int = settings.DB_POOL_TIMEOUT,
) -> Engine:
    """
    Creates and returns a SQLAlchemy Engine object for connecting to a database.

    Parameters:
        database_url (str): The URL of the database to connect to.
        Defaults to SQLALCHEMY_DATABASE_URL.
        echo (bool): Whether or not to enable echoing of SQL statements.
        Defaults to False.
        pool_size (int): Number of connections kept open in the pool.
        max_overflow (int): Extra connections allowed beyond pool_size under load.
        pool_timeout (int): Seconds to wait for a connection before raising a timeout.

    Returns:
        Engine: A SQLAlchemy Engine object representing the database connection.
    """
    engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,  # Verify connections before using them
        pool_recycle=3600,  # Recycle connections after 1 hour to avoid stale connections
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
    )
    return engine


def get_local_session(database_url: str, echo=False, **kwargs) -> sessionmaker:
    """
    Create and return a sessionmaker object for a local database session.

    Parameters:
        database_url (str): The URL of the local database.
        Defaults to `SQLALCHEMY_DATABASE_URL`.
        echo (bool): Whether to echo SQL statements to the console.
        Defaults to `False`.

    Returns:
        sessionmaker: A sessionmaker object configured for the local database session.
    """
    engine = get_engine(database_url, echo)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session


SQLALCHEMY_DATABASE_URL = build_sqlalchemy_database_url_from_env(settings)

# Create a single engine and sessionmaker to be reused across all requests
engine = get_engine(SQLALCHEMY_DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)