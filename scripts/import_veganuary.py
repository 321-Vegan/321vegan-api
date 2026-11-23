"""Stores the Veganuary weeks given (the app's lib/assets/veganuary/weekN.json),
creating or replacing each one: the app then downloads them at its next
launch. Run the app's tests on them first (test/models/veganuary_test.dart).

    docker cp ../321vegan-app/flutter_app/lib/assets/veganuary 321veganapi:/tmp/veganuary
    docker exec 321veganapi poetry run python -m scripts.import_veganuary /tmp/veganuary/week*.json
"""
import json
import sys
from functools import partial

from src.app.config import settings
from src.app.crud.veganuary_week import veganuary_week_crud
from src.app.database.db import get_ctx_db
from src.app.database.session import build_sqlalchemy_database_url_from_env
from src.app.log import get_logger

log = get_logger(__name__)

DATABASE_URL = build_sqlalchemy_database_url_from_env(settings)


def import_weeks(paths: list[str]) -> None:
    weeks = []
    for path in paths:
        with open(path, encoding="utf-8") as file:
            content = json.load(file)
        number = content.get("number")
        if not isinstance(number, int) or not content.get("days"):
            raise SystemExit(f"{path}: not a Veganuary week (number, days)")
        weeks.append((number, content))
    get_db = partial(get_ctx_db, database_url=DATABASE_URL)
    with get_db() as db:
        for number, content in weeks:
            veganuary_week_crud.upsert(db, number, content)
            print(f"Week {number} saved")
        print(f"Version: {veganuary_week_crud.version(db)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m scripts.import_veganuary week1.json [week2.json …]")
    import_weeks(sys.argv[1:])
