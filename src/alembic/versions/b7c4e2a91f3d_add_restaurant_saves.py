"""add restaurant saves

Revision ID: b7c4e2a91f3d
Revises: 573a11c56d86
Create Date: 2026-10-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e2a91f3d'
down_revision: Union[str, None] = '573a11c56d86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('restaurant_saves',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('restaurant_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'restaurant_id', name='uq_restaurant_save_user_restaurant')
    )
    op.create_index(op.f('ix_restaurant_saves_created_at'), 'restaurant_saves', ['created_at'], unique=False)
    op.create_index(op.f('ix_restaurant_saves_id'), 'restaurant_saves', ['id'], unique=False)
    op.create_index(op.f('ix_restaurant_saves_restaurant_id'), 'restaurant_saves', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_restaurant_saves_user_id'), 'restaurant_saves', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_restaurant_saves_user_id'), table_name='restaurant_saves')
    op.drop_index(op.f('ix_restaurant_saves_restaurant_id'), table_name='restaurant_saves')
    op.drop_index(op.f('ix_restaurant_saves_id'), table_name='restaurant_saves')
    op.drop_index(op.f('ix_restaurant_saves_created_at'), table_name='restaurant_saves')
    op.drop_table('restaurant_saves')
