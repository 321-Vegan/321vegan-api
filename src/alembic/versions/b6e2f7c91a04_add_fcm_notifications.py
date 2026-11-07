"""add durable notifications and FCM delivery

Revision ID: b6e2f7c91a04
Revises: a5c2c8890c03
Create Date: 2026-11-07 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6e2f7c91a04"
down_revision: Union[str, None] = "a5c2c8890c03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_notifications_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
    )
    op.create_index(
        op.f("ix_notifications_id"),
        "notifications",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_id_id",
        "notifications",
        ["user_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_expires_at",
        "notifications",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "push_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("installation_id", sa.String(length=255), nullable=True),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_push_devices_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_push_devices"),
        sa.UniqueConstraint(
            "installation_id",
            name="uq_push_devices_installation_id",
        ),
        sa.UniqueConstraint("token", name="uq_push_devices_token"),
    )
    op.create_index(
        op.f("ix_push_devices_id"),
        "push_devices",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_push_devices_user_enabled",
        "push_devices",
        ["user_id", "enabled"],
        unique=False,
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["push_devices.id"],
            name="fk_notification_deliveries_device_id_push_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name="fk_notification_deliveries_notification_id_notifications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
        sa.UniqueConstraint(
            "notification_id",
            "device_id",
            name="uq_notification_deliveries_notification_device",
        ),
    )
    op.create_index(
        op.f("ix_notification_deliveries_id"),
        "notification_deliveries",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_status_next_attempt",
        "notification_deliveries",
        ["status", "next_attempt_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_status_next_attempt",
        table_name="notification_deliveries",
    )
    op.drop_index(
        op.f("ix_notification_deliveries_id"),
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
    op.drop_index("ix_push_devices_user_enabled", table_name="push_devices")
    op.drop_index(op.f("ix_push_devices_id"), table_name="push_devices")
    op.drop_table("push_devices")
    op.drop_index("ix_notifications_expires_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id_id", table_name="notifications")
    op.drop_index(op.f("ix_notifications_id"), table_name="notifications")
    op.drop_table("notifications")
