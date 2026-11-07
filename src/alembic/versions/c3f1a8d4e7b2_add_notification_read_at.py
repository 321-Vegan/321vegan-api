"""add notification read_at

Revision ID: c3f1a8d4e7b2
Revises: b6e2f7c91a04
Create Date: 2026-11-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f1a8d4e7b2"
down_revision: Union[str, None] = "b6e2f7c91a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "read_at")
