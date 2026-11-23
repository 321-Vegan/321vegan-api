"""One-off: moves the course's images from the app (lib/assets/images/veganuary/)
to the bucket, under veganuary/, and points the weeks stored here at them.

Each image keeps its name ("veganuary/cover-l-amorce.webp"), uploaded as is
(already WebP); the weeks' "lib/assets/images/veganuary/<name>" become
"veganuary/<name>". Other app assets (characters, icons) stay as they are.
Without --apply, only says what it would do.

    docker cp ../321vegan-app/flutter_app/lib/assets/images/veganuary 321veganapi:/tmp/veganuary-images
    docker exec 321veganapi poetry run python -m scripts.migrate_veganuary_images /tmp/veganuary-images
    docker exec 321veganapi poetry run python -m scripts.migrate_veganuary_images /tmp/veganuary-images --apply
"""
import json
import sys
from functools import partial
from pathlib import Path

from src.app.config import settings
from src.app.crud.veganuary_week import veganuary_week_crud
from src.app.database.db import get_ctx_db
from src.app.database.session import build_sqlalchemy_database_url_from_env
from src.app.services.s3_file_manager import s3_file_manager

DATABASE_URL = build_sqlalchemy_database_url_from_env(settings)
APP_FOLDER = "lib/assets/images/veganuary/"
PREFIX = "veganuary/"


def _replace(value, paths: dict[str, str]):
    """[value] (a week's JSON) with the app paths of [paths] replaced."""
    if isinstance(value, str):
        return paths.get(value, value)
    if isinstance(value, list):
        return [_replace(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, paths) for key, item in value.items()}
    return value


def migrate(folder: str, apply: bool) -> None:
    images = sorted(Path(folder).glob("*.webp"))
    if not images:
        raise SystemExit(f"No .webp image in {folder}")
    paths = {f"{APP_FOLDER}{image.name}": f"{PREFIX}{image.name}" for image in images}

    get_db = partial(get_ctx_db, database_url=DATABASE_URL)
    with get_db() as db:
        weeks = veganuary_week_crud.get_all_ordered(db)
        used = {
            path
            for week in weeks
            for path in paths
            if path in json.dumps(week.content, ensure_ascii=False)
        }
        missing = {
            app_path
            for week in weeks
            for app_path in _app_images(week.content)
            if app_path not in paths
        }
        print(f"{len(images)} images, {len(used)} used by the weeks")
        if missing:
            print("Used by the weeks but not in the folder (left as is):")
            for path in sorted(missing):
                print(f"  {path}")
        if not apply:
            print("Dry run: add --apply to upload and update the weeks")
            return

        for image in images:
            with image.open("rb") as file:
                s3_file_manager.s3_client.upload_fileobj(
                    file,
                    s3_file_manager.bucket_name,
                    paths[f"{APP_FOLDER}{image.name}"],
                    ExtraArgs={
                        "ACL": "public-read",
                        "ContentType": "image/webp",
                        "CacheControl": "public, max-age=31536000, immutable",
                    },
                )
        print(f"{len(images)} images uploaded under {PREFIX}")

        for week in weeks:
            content = _replace(week.content, paths)
            if content != week.content:
                veganuary_week_crud.upsert(db, week.number, content)
                print(f"Week {week.number} updated")
        print(f"Version: {veganuary_week_crud.version(db)}")


def _app_images(value):
    if isinstance(value, str):
        if value.startswith(APP_FOLDER):
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _app_images(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _app_images(item)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python -m scripts.migrate_veganuary_images <folder> [--apply]"
        )
    migrate(sys.argv[1], apply="--apply" in sys.argv[2:])
