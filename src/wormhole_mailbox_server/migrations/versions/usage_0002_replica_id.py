"""usage schema v3: attribute every row to a replica

Revision ID: usage_0002
Revises: usage_0001
Create Date: 2026-11-08

Every usage table gains a ``replica_id`` column naming the persistent
identity of the replica that wrote the row. ``current`` is keyed by
``replica_id`` alone; the append-only event tables gain a generated UUID
``id`` and use ``(replica_id, id)`` as their primary key.

Rows written before this migration are attributed to a synthetic
``"legacy"`` replica so existing installations keep their history.
"""

import sqlalchemy as sa


revision = "usage_0002"
down_revision = "usage_0001"
branch_labels = None
depends_on = None

LEGACY_REPLICA_ID = "legacy"


def _fetch(bind, sql):
    return bind.execute(sa.text(sql)).mappings().all()


def _insert(bind, sql, **values):
    bind.execute(sa.text(sql), values)


def upgrade(op):
    bind = op.get_bind()

    # -- replicas: one row per replica sharing this database ------------
    op.create_table(
        "replicas",
        sa.Column("replica_id", sa.String(64), primary_key=True),
        sa.Column("hostname", sa.String(255)),
    )

    # -- current: one row per replica ------------------------------------
    op.rename_table("current", "current_usage_old")
    op.create_table(
        "current",
        sa.Column("replica_id", sa.String(64), primary_key=True),
        sa.Column("rebooted", sa.Integer()),
        sa.Column("updated", sa.Integer()),
        sa.Column("blur_time", sa.Integer()),
        sa.Column("connections_websocket", sa.Integer()),
    )
    for i, row in enumerate(_fetch(
            bind,
            "SELECT rebooted, updated, blur_time, connections_websocket"
            " FROM current_usage_old")):
        replica_id = LEGACY_REPLICA_ID if i == 0 else "%s-%d" % (
            LEGACY_REPLICA_ID, i)
        _insert(
            bind,
            "INSERT INTO current"
            " (replica_id, rebooted, updated, blur_time,"
            "  connections_websocket)"
            " VALUES (:replica_id, :rebooted, :updated, :blur_time,"
            "         :connections_websocket)",
            replica_id=replica_id,
            rebooted=row["rebooted"],
            updated=row["updated"],
            blur_time=row["blur_time"],
            connections_websocket=row["connections_websocket"],
        )
    op.drop_table("current_usage_old")

    # -- nameplates -------------------------------------------------------
    op.drop_index("nameplates_idx", table_name="nameplates")
    op.rename_table("nameplates", "nameplates_usage_old")
    op.create_table(
        "nameplates",
        sa.Column("id", sa.Integer(), primary_key=True,
                  autoincrement=True),
        sa.Column("replica_id", sa.String(64)),
        sa.Column("app_id", sa.String(255)),
        sa.Column("started", sa.Integer()),
        sa.Column("waiting_time", sa.Integer()),
        sa.Column("total_time", sa.Integer()),
        sa.Column("result", sa.String(64)),
    )
    op.create_index("nameplates_idx", "nameplates", ["app_id", "started"])
    op.create_index("nameplates_replica_idx", "nameplates", ["replica_id"])
    for row in _fetch(
            bind,
            "SELECT app_id, started, waiting_time, total_time, result"
            " FROM nameplates_usage_old"):
        _insert(
            bind,
            "INSERT INTO nameplates"
            " (replica_id, app_id, started, waiting_time, total_time,"
            "  result)"
            " VALUES (:replica_id, :app_id, :started, :waiting_time,"
            "         :total_time, :result)",
            replica_id=LEGACY_REPLICA_ID,
            app_id=row["app_id"],
            started=row["started"],
            waiting_time=row["waiting_time"],
            total_time=row["total_time"],
            result=row["result"],
        )
    op.drop_table("nameplates_usage_old")

    # -- mailboxes --------------------------------------------------------
    op.drop_index("mailboxes_result_idx", table_name="mailboxes")
    op.drop_index("mailboxes_idx", table_name="mailboxes")
    op.rename_table("mailboxes", "mailboxes_usage_old")
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Integer(), primary_key=True,
                  autoincrement=True),
        sa.Column("replica_id", sa.String(64)),
        sa.Column("app_id", sa.String(255)),
        sa.Column("for_nameplate", sa.Boolean()),
        sa.Column("started", sa.Integer()),
        sa.Column("total_time", sa.Integer()),
        sa.Column("waiting_time", sa.Integer()),
        sa.Column("result", sa.String(64)),
    )
    op.create_index("mailboxes_idx", "mailboxes", ["app_id", "started"])
    op.create_index("mailboxes_result_idx", "mailboxes", ["result"])
    op.create_index("mailboxes_replica_idx", "mailboxes", ["replica_id"])
    for row in _fetch(
            bind,
            "SELECT app_id, for_nameplate, started, total_time,"
            " waiting_time, result FROM mailboxes_usage_old"):
        _insert(
            bind,
            "INSERT INTO mailboxes"
            " (replica_id, app_id, for_nameplate, started, total_time,"
            "  waiting_time, result)"
            " VALUES (:replica_id, :app_id, :for_nameplate, :started,"
            "         :total_time, :waiting_time, :result)",
            replica_id=LEGACY_REPLICA_ID,
            app_id=row["app_id"],
            for_nameplate=row["for_nameplate"],
            started=row["started"],
            total_time=row["total_time"],
            waiting_time=row["waiting_time"],
            result=row["result"],
        )
    op.drop_table("mailboxes_usage_old")

    # -- client_versions --------------------------------------------------
    op.drop_index("client_versions_appid_time_idx",
                  table_name="client_versions")
    op.drop_index("client_versions_time_idx", table_name="client_versions")
    op.rename_table("client_versions", "client_versions_usage_old")
    op.create_table(
        "client_versions",
        sa.Column("id", sa.Integer(), primary_key=True,
                  autoincrement=True),
        sa.Column("replica_id", sa.String(64)),
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
    op.create_index("client_versions_replica_idx", "client_versions",
                    ["replica_id"])
    for row in _fetch(
            bind,
            "SELECT app_id, side, connect_time, implementation, version"
            " FROM client_versions_usage_old"):
        _insert(
            bind,
            "INSERT INTO client_versions"
            " (replica_id, app_id, side, connect_time, implementation,"
            "  version)"
            " VALUES (:replica_id, :app_id, :side, :connect_time,"
            "         :implementation, :version)",
            replica_id=LEGACY_REPLICA_ID,
            app_id=row["app_id"],
            side=row["side"],
            connect_time=row["connect_time"],
            implementation=row["implementation"],
            version=row["version"],
        )
    op.drop_table("client_versions_usage_old")


def downgrade(op):
    bind = op.get_bind()

    # -- current ----------------------------------------------------------
    op.rename_table("current", "current_usage_v3")
    op.create_table(
        "current",
        sa.Column("rebooted", sa.Integer()),
        sa.Column("updated", sa.Integer()),
        sa.Column("blur_time", sa.Integer()),
        sa.Column("connections_websocket", sa.Integer()),
    )
    for row in _fetch(
            bind,
            "SELECT rebooted, updated, blur_time, connections_websocket"
            " FROM current_usage_v3"):
        _insert(
            bind,
            "INSERT INTO current"
            " (rebooted, updated, blur_time, connections_websocket)"
            " VALUES (:rebooted, :updated, :blur_time,"
            "         :connections_websocket)",
            rebooted=row["rebooted"],
            updated=row["updated"],
            blur_time=row["blur_time"],
            connections_websocket=row["connections_websocket"],
        )
    op.drop_table("current_usage_v3")

    # -- nameplates -------------------------------------------------------
    op.drop_index("nameplates_replica_idx", table_name="nameplates")
    op.drop_index("nameplates_idx", table_name="nameplates")
    op.rename_table("nameplates", "nameplates_usage_v3")
    op.create_table(
        "nameplates",
        sa.Column("app_id", sa.String(255)),
        sa.Column("started", sa.Integer()),
        sa.Column("waiting_time", sa.Integer()),
        sa.Column("total_time", sa.Integer()),
        sa.Column("result", sa.String(64)),
    )
    op.create_index("nameplates_idx", "nameplates", ["app_id", "started"])
    for row in _fetch(
            bind,
            "SELECT app_id, started, waiting_time, total_time, result"
            " FROM nameplates_usage_v3"):
        _insert(
            bind,
            "INSERT INTO nameplates"
            " (app_id, started, waiting_time, total_time, result)"
            " VALUES (:app_id, :started, :waiting_time, :total_time,"
            "         :result)",
            app_id=row["app_id"],
            started=row["started"],
            waiting_time=row["waiting_time"],
            total_time=row["total_time"],
            result=row["result"],
        )
    op.drop_table("nameplates_usage_v3")

    # -- mailboxes --------------------------------------------------------
    op.drop_index("mailboxes_replica_idx", table_name="mailboxes")
    op.drop_index("mailboxes_result_idx", table_name="mailboxes")
    op.drop_index("mailboxes_idx", table_name="mailboxes")
    op.rename_table("mailboxes", "mailboxes_usage_v3")
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
    for row in _fetch(
            bind,
            "SELECT app_id, for_nameplate, started, total_time,"
            " waiting_time, result FROM mailboxes_usage_v3"):
        _insert(
            bind,
            "INSERT INTO mailboxes"
            " (app_id, for_nameplate, started, total_time, waiting_time,"
            "  result)"
            " VALUES (:app_id, :for_nameplate, :started, :total_time,"
            "         :waiting_time, :result)",
            app_id=row["app_id"],
            for_nameplate=row["for_nameplate"],
            started=row["started"],
            total_time=row["total_time"],
            waiting_time=row["waiting_time"],
            result=row["result"],
        )
    op.drop_table("mailboxes_usage_v3")

    # -- client_versions --------------------------------------------------
    op.drop_index("client_versions_replica_idx",
                  table_name="client_versions")
    op.drop_index("client_versions_appid_time_idx",
                  table_name="client_versions")
    op.drop_index("client_versions_time_idx", table_name="client_versions")
    op.rename_table("client_versions", "client_versions_usage_v3")
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
    for row in _fetch(
            bind,
            "SELECT app_id, side, connect_time, implementation, version"
            " FROM client_versions_usage_v3"):
        _insert(
            bind,
            "INSERT INTO client_versions"
            " (app_id, side, connect_time, implementation, version)"
            " VALUES (:app_id, :side, :connect_time, :implementation,"
            "         :version)",
            app_id=row["app_id"],
            side=row["side"],
            connect_time=row["connect_time"],
            implementation=row["implementation"],
            version=row["version"],
        )
    op.drop_table("client_versions_usage_v3")

    op.drop_table("replicas")
