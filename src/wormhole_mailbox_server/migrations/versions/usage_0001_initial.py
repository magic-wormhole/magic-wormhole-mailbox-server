"""initial usage schema

Revision ID: usage_0001
Revises:
Create Date: 2026-11-08
"""

import sqlalchemy as sa


revision = "usage_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(op):
    op.create_table(
        "current",
        sa.Column("rebooted", sa.Integer()),
        sa.Column("updated", sa.Integer()),
        sa.Column("blur_time", sa.Integer()),
        sa.Column("connections_websocket", sa.Integer()),
    )

    op.create_table(
        "nameplates",
        sa.Column("app_id", sa.String(255)),
        sa.Column("started", sa.Integer()),
        sa.Column("waiting_time", sa.Integer()),
        sa.Column("total_time", sa.Integer()),
        sa.Column("result", sa.String(64)),
    )
    op.create_index("nameplates_idx", "nameplates", ["app_id", "started"])

    op.create_table(
        "mailboxes",
        sa.Column("app_id", sa.String(255)),
        sa.Column("for_nameplate", sa.Boolean()),
        sa.Column("started", sa.Integer()),
        sa.Column("total_time", sa.Integer()),
        sa.Column("waiting_time", sa.Integer()),
        sa.Column("result", sa.String(64)),
    )
    op.create_index("mailboxes_idx", "mailboxes", ["app_id", "started"])
    op.create_index("mailboxes_result_idx", "mailboxes", ["result"])

    op.create_table(
        "client_versions",
        sa.Column("app_id", sa.String(255)),
        sa.Column("side", sa.String(255)),
        sa.Column("connect_time", sa.Integer()),
        sa.Column("implementation", sa.String(255)),
        sa.Column("version", sa.String(64)),
    )
    op.create_index("client_versions_time_idx", "client_versions",
                    ["connect_time"])
    op.create_index("client_versions_appid_time_idx", "client_versions",
                    ["app_id", "connect_time"])


def downgrade(op):
    op.drop_index("client_versions_appid_time_idx",
                  table_name="client_versions")
    op.drop_index("client_versions_time_idx", table_name="client_versions")
    op.drop_table("client_versions")
    op.drop_index("mailboxes_result_idx", table_name="mailboxes")
    op.drop_index("mailboxes_idx", table_name="mailboxes")
    op.drop_table("mailboxes")
    op.drop_index("nameplates_idx", table_name="nameplates")
    op.drop_table("nameplates")
    op.drop_table("current")
