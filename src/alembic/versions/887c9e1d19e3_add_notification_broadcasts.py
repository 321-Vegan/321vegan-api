"""add notification broadcasts

Revision ID: 887c9e1d19e3
Revises: 441c1060fb77
Create Date: 2026-11-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '887c9e1d19e3'
down_revision: Union[str, None] = '441c1060fb77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'notification_broadcasts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('recipient_count', sa.Integer(), nullable=False),
        sa.Column('sent_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['sent_by_id'], ['users.id'], ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_notification_broadcasts_id'),
        'notification_broadcasts',
        ['id'],
        unique=False,
    )
    op.add_column(
        'notifications',
        sa.Column('broadcast_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_notifications_broadcast_id_notification_broadcasts',
        'notifications',
        'notification_broadcasts',
        ['broadcast_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_notifications_broadcast_id'),
        'notifications',
        ['broadcast_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_notifications_broadcast_id'), table_name='notifications')
    op.drop_constraint(
        'fk_notifications_broadcast_id_notification_broadcasts',
        'notifications',
        type_='foreignkey',
    )
    op.drop_column('notifications', 'broadcast_id')
    op.drop_index(
        op.f('ix_notification_broadcasts_id'),
        table_name='notification_broadcasts',
    )
    op.drop_table('notification_broadcasts')
