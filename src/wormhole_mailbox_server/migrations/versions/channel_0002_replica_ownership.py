"""channel schema: replica ownership and liveness

Revision ID: channel_0002
Revises: channel_0001
Create Date: 2026-11-08

Adds a ``replicas`` registry with a heartbeat and stamps each connection row
with the replica that owns it. Live connections are now a global view:
join ``connections`` to ``replicas`` and keep only rows whose replica has a
fresh heartbeat.
"""

import sqlalchemy as sa


revision = "channel_0002"
down_revision = "channel_0001"
branch_labels = None
depends_on = None


def upgrade(op):
    op.create_table(
        "replicas",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("started", sa.Integer()),
        sa.Column("heartbeat", sa.Integer()),
        sa.Column("host", sa.String(255)),
        sa.Column("pid", sa.Integer()),
    )
    op.create_index("replicas_heartbeat_idx", "replicas", ["heartbeat"])

    op.add_column("connections", sa.Column("replica_id", sa.String(64)))
    op.create_index("connections_replica_idx", "connections", ["replica_id"])
    op.create_index("connections_active_idx", "connections", ["active"])
    op.create_index("connection_messages_id_idx", "connection_messages",
                    ["id", "when"])

    # Connection rows are transient live state. Startup used to clear them
    # unconditionally; now that cleanup is replica-scoped, discard the
    # unowned rows from before this migration.
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM connection_messages"))
    bind.execute(sa.text("DELETE FROM connections"))


def downgrade(op):
    op.drop_index("connection_messages_id_idx",
                  table_name="connection_messages")
    op.drop_index("connections_active_idx", table_name="connections")
    op.drop_index("connections_replica_idx", table_name="connections")
    op.drop_column("connections", "replica_id")
    op.drop_index("replicas_heartbeat_idx", table_name="replicas")
    op.drop_table("replicas")
