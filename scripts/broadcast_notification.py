"""Send one notification to every account with pushes turned on, as the
admin tool's notifications page does (kept in its history).

It lands in each account's notification center and is queued for its
devices; the FCM worker sends the pushes. Dry run unless --send is given:

    poetry run python -m scripts.broadcast_notification \\
        --title "Le Parcours 321 Vegan commence !" \\
        --body "C'est le jour 1 : rendez-vous dans l'app." --send
"""
import argparse

from app.database.session import SessionLocal
from app.log import get_logger
from app.services.notification_broadcast import notification_broadcast_service


log = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Notify every account with pushes turned on",
    )
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Really send (otherwise only counts the recipients)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if not args.send:
            count = len(notification_broadcast_service.recipient_ids(db))
            print(f"Would notify {count} accounts (add --send to send)")
            return
        broadcast = notification_broadcast_service.send(
            db, title=args.title, body=args.body, sent_by_id=None,
        )
        log.info("Broadcast %s sent from the command line", broadcast.id)
        print(f"Notified {broadcast.recipient_count} accounts")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
