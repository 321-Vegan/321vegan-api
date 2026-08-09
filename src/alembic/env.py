from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from dotenv import load_dotenv
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
sys.path.append(BASE_DIR)
# sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# this will overwrite the ini-file sqlalchemy.url path
# with the path given in the config of the main code
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from src.app.models import Base
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Local dev DBs can carry schema from unmerged feature branches (e.g. the
# XP tables/columns from feature/implement-xp-system, which isn't on main
# yet). Autogenerate compares the live DB against these models and would
# otherwise propose dropping that leftover schema on every new migration.
# Remove this filter once that feature actually merges into main.
EXCLUDED_TABLES = {"xp_action_types", "xp_events"}
EXCLUDED_COLUMNS = {
    ("users", "xp"),
    ("users", "login_streak_count"),
    ("users", "last_login_streak_date"),
}

# ix_scan_events_ean_shop_id is created via a raw op.create_index() in that
# same XP migration rather than being declared on the ScanEvent model, so
# it's permanently invisible to Base.metadata -- this one is a standing
# false positive independent of the XP branch situation above, and should
# stay excluded unless it's later added as a proper Index() on the model.
EXCLUDED_INDEXES = {"ix_scan_events_ean_shop_id"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in EXCLUDED_TABLES:
        return False
    if type_ == "column" and (object.table.name, name) in EXCLUDED_COLUMNS:
        return False
    if type_ == "index" and name in EXCLUDED_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
