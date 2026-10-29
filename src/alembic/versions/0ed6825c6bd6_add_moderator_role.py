"""add moderator role

Revision ID: 0ed6825c6bd6
Revises: 98824c98c85a
Create Date: 2026-10-29 12:57:53.469727

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0ed6825c6bd6'
down_revision: Union[str, None] = '98824c98c85a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate doesn't detect new enum values
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'MODERATOR'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL does not support removing enum values; no-op
    pass
