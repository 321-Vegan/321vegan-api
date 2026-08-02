"""dedup apple notif

Revision ID: 4e68f9a1447f
Revises: 216ecef1f6d7
Create Date: 2026-08-02 11:07:28.976747

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4e68f9a1447f'
down_revision: Union[str, None] = '216ecef1f6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('subscriptions', sa.Column('last_notification_uuid', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('subscriptions', 'last_notification_uuid')
