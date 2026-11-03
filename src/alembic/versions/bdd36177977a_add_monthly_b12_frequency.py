"""add monthly b12 frequency

Revision ID: bdd36177977a
Revises: d1ad90d49544
Create Date: 2026-11-03 09:25:06.354207

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bdd36177977a'
down_revision: Union[str, None] = 'd1ad90d49544'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate doesn't detect new enum values: added by hand.
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("ALTER TYPE b12intakefrequency ADD VALUE IF NOT EXISTS 'MONTHLY'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op
    pass
