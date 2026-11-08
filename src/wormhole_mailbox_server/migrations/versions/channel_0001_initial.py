"""initial channel schema

Revision ID: channel_0001
Revises:
Create Date: 2026-11-08
"""

from alembic import op
import sqlalchemy as sa


revision = "channel_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mailboxes",
        sa.Column("app_id", sa.String()),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("updated", sa.Integer()),
        sa.Column("for_nameplate", sa.Boolean()),
    )
    op.create_index("mailboxes_idx", "mailboxes", ["app_id", "id"])

    op.create_table(
        "nameplates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("app_id", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("mailbox_id", sa.String()),
        sa.Column("request_id", sa.String()),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"]),
    )
    op.create_index("nameplates_idx", "nameplates", ["app_id", "name"])
    op.create_index("nameplates_mailbox_idx", "nameplates",
                    ["app_id", "mailbox_id"])
    op.create_index("nameplates_request_idx", "nameplates",
                    ["app_id", "request_id"])

    op.create_table(
        "nameplate_sides",
        sa.Column("nameplates_id", sa.Integer()),
        sa.Column("claimed", sa.Boolean()),
        sa.Column("side", sa.String()),
        sa.Column("added", sa.Integer()),
        sa.ForeignKeyConstraint(["nameplates_id"], ["nameplates.id"]),
    )

    op.create_table(
        "mailbox_sides",
        sa.Column("mailbox_id", sa.String()),
        sa.Column("opened", sa.Boolean()),
        sa.Column("side", sa.String()),
        sa.Column("added", sa.Integer()),
        sa.Column("mood", sa.String()),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"]),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("app_id", sa.String()),
        sa.Column("mailbox_id", sa.String()),
        sa.Column("side", sa.String()),
        sa.Column("phase", sa.String()),
        sa.Column("body", sa.String()),
        sa.Column("server_rx", sa.Integer()),
        sa.Column("msg_id", sa.String()),
    )
    op.create_index("messages_idx", "messages", ["app_id", "mailbox_id"])

    op.create_table(
        "addrid_generation",
        sa.Column("generation", sa.Integer()),
        sa.Column("started", sa.Integer()),
    )

    op.create_table(
        "connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("addrid_generation", sa.Integer()),
        sa.Column("addrid_counter", sa.Integer()),
        sa.Column("connected", sa.Integer()),
        sa.Column("side", sa.String()),
        sa.Column("implementation", sa.String()),
        sa.Column("version", sa.String()),
        sa.Column("active", sa.Integer()),
    )

    op.create_table(
        "connection_messages",
        sa.Column("id", sa.Integer()),
        sa.Column("when", sa.Integer()),
        sa.Column("name", sa.String()),
        sa.ForeignKeyConstraint(["id"], ["connections.id"]),
    )


def downgrade():
    op.drop_table("connection_messages")
    op.drop_table("connections")
    op.drop_table("addrid_generation")
    op.drop_index("messages_idx", table_name="messages")
    op.drop_table("messages")
    op.drop_table("mailbox_sides")
    op.drop_table("nameplate_sides")
    op.drop_index("nameplates_request_idx", table_name="nameplates")
    op.drop_index("nameplates_mailbox_idx", table_name="nameplates")
    op.drop_index("nameplates_idx", table_name="nameplates")
    op.drop_table("nameplates")
    op.drop_index("mailboxes_idx", table_name="mailboxes")
    op.drop_table("mailboxes")
