"""add veganuary weeks

Revision ID: b3ac40868714
Revises: e88f43a3d7f7
Create Date: 2026-11-23 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3ac40868714'
down_revision: Union[str, None] = 'e88f43a3d7f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'veganuary_weeks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_veganuary_weeks_id'), 'veganuary_weeks', ['id'], unique=False)
    op.create_index(op.f('ix_veganuary_weeks_number'), 'veganuary_weeks', ['number'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_veganuary_weeks_number'), table_name='veganuary_weeks')
    op.drop_index(op.f('ix_veganuary_weeks_id'), table_name='veganuary_weeks')
    op.drop_table('veganuary_weeks')
