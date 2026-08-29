"""add TO_INVESTIGATE to product state

Revision ID: 4e9e3e5878d1
Revises: b32cb864d000
Create Date: 2026-08-28 07:23:44.283233

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e9e3e5878d1'
down_revision: Union[str, None] = 'b32cb864d000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Alembic autogenerate does not detect new values on a Postgres ENUM.
    op.execute(
        "ALTER TYPE productstate ADD VALUE IF NOT EXISTS 'TO_INVESTIGATE' "
        "BEFORE 'WAITING_PUBLISH'"
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no ``ALTER TYPE ... DROP VALUE``; the enum has to be
    recreated without the value. This fails if any row still uses
    ``TO_INVESTIGATE`` - move those products to another state first.
    """
    op.execute("ALTER TYPE productstate RENAME TO productstate_old")
    op.execute(
        "CREATE TYPE productstate AS ENUM("
        "'CREATED', 'NEED_CONTACT', 'WAITING_REPLY', 'NOT_FOUND', "
        "'WAITING_PUBLISH', 'PUBLISHED')"
    )
    op.execute("ALTER TABLE products ALTER COLUMN state DROP DEFAULT")
    op.execute(
        "ALTER TABLE products ALTER COLUMN state TYPE productstate "
        "USING state::text::productstate"
    )
    op.execute("ALTER TABLE products ALTER COLUMN state SET DEFAULT 'CREATED'")
    op.execute("DROP TYPE productstate_old")
