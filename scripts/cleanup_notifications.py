from app.crud.notification import notification_crud
from app.database.session import SessionLocal
from app.log import get_logger


log = get_logger(__name__)


def cleanup_notifications() -> int:
    """Delete notifications whose retention period has elapsed."""
    db = SessionLocal()
    try:
        deleted_count = notification_crud.delete_expired(db)
        db.commit()
        log.info("Deleted %s expired notifications", deleted_count)
        return deleted_count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    cleanup_notifications()
