"""add veganuary days

Revision ID: 441c1060fb77
Revises: b3ac40868714
Create Date: 2026-11-23 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '441c1060fb77'
down_revision: Union[str, None] = 'b3ac40868714'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'veganuary_days',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Integer(), nullable=False),
        sa.Column('completed_on', sa.Date(), nullable=False),
        sa.Column('myth_id', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'day'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('veganuary_days')
