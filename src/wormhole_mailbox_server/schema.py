"""SQLAlchemy Core schema definitions for the three databases.

The logical schema matches the historical SQLite schema in ``db-schemas/``:
same tables, columns, constraints, and indexes. Types are declared
explicitly, including string lengths, so the same definitions compile on
SQLite, PostgreSQL, and MySQL.

The schema is split into three ``MetaData`` objects because the server uses
three separate databases (channel, usage, and address-id).
"""

from sqlalchemy import (Boolean, Column, ForeignKey, Index, Integer,
                        MetaData, String, Table, Text)


# -- channel database ----------------------------------------------------

channel_metadata = MetaData()

nameplates = Table(
    "nameplates", channel_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("app_id", String(255)),
    Column("name", String(255)),
    Column("mailbox_id", String(64), ForeignKey("mailboxes.id")),
    Column("request_id", String(255)),
)
Index("nameplates_idx", nameplates.c.app_id, nameplates.c.name)
Index("nameplates_mailbox_idx", nameplates.c.app_id, nameplates.c.mailbox_id)
Index("nameplates_request_idx", nameplates.c.app_id, nameplates.c.request_id)

mailboxes = Table(
    "mailboxes", channel_metadata,
    Column("app_id", String(255)),
    Column("id", String(64), primary_key=True),
    Column("updated", Integer),
    Column("for_nameplate", Boolean),
)
Index("mailboxes_idx", mailboxes.c.app_id, mailboxes.c.id)

nameplate_sides = Table(
    "nameplate_sides", channel_metadata,
    Column("nameplates_id", Integer, ForeignKey("nameplates.id")),
    Column("claimed", Boolean),
    Column("side", String(255)),
    Column("added", Integer),
)

mailbox_sides = Table(
    "mailbox_sides", channel_metadata,
    Column("mailbox_id", String(64), ForeignKey("mailboxes.id")),
    Column("opened", Boolean),
    Column("side", String(255)),
    Column("added", Integer),
    Column("mood", String(64)),
)

messages = Table(
    "messages", channel_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("app_id", String(255)),
    Column("mailbox_id", String(64)),
    Column("side", String(255)),
    Column("phase", String(255)),
    Column("body", Text()),
    Column("server_rx", Integer),
    Column("msg_id", String(255)),
)
Index("messages_idx", messages.c.app_id, messages.c.mailbox_id)

addrid_generation = Table(
    "addrid_generation", channel_metadata,
    Column("generation", Integer),
    Column("started", Integer),
)

connections = Table(
    "connections", channel_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("addrid_generation", Integer),
    Column("addrid_counter", Integer),
    Column("connected", Integer),
    Column("side", String(255)),
    Column("implementation", String(255)),
    Column("version", String(64)),
    Column("active", Integer),
)

connection_messages = Table(
    "connection_messages", channel_metadata,
    Column("id", Integer, ForeignKey("connections.id")),
    Column("when", Integer),
    Column("name", String(255)),
)


# -- usage database ------------------------------------------------------

usage_metadata = MetaData()

# ``current`` is replica-scoped: each replica maintains its own row and the
# primary key is the replica identity. The event tables are shared,
# append-only history: an autoincrement ``id`` is the primary key and
# ``replica_id`` is non-key attribution metadata for the replica that wrote
# the row.

current = Table(
    "current", usage_metadata,
    Column("replica_id", String(64), primary_key=True),
    Column("rebooted", Integer),
    Column("updated", Integer),
    Column("blur_time", Integer),
    Column("connections_websocket", Integer),
)

usage_replicas = Table(
    "replicas", usage_metadata,
    Column("replica_id", String(64), primary_key=True),
    Column("hostname", String(255)),
)

usage_nameplates = Table(
    "nameplates", usage_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("replica_id", String(64)),
    Column("app_id", String(255)),
    Column("started", Integer),
    Column("waiting_time", Integer),
    Column("total_time", Integer),
    Column("result", String(64)),
)
Index("nameplates_idx", usage_nameplates.c.app_id,
      usage_nameplates.c.started)
Index("nameplates_replica_idx", usage_nameplates.c.replica_id)

usage_mailboxes = Table(
    "mailboxes", usage_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("replica_id", String(64)),
    Column("app_id", String(255)),
    Column("for_nameplate", Boolean),
    Column("started", Integer),
    Column("total_time", Integer),
    Column("waiting_time", Integer),
    Column("result", String(64)),
)
Index("mailboxes_idx", usage_mailboxes.c.app_id, usage_mailboxes.c.started)
Index("mailboxes_result_idx", usage_mailboxes.c.result)
Index("mailboxes_replica_idx", usage_mailboxes.c.replica_id)

client_versions = Table(
    "client_versions", usage_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("replica_id", String(64)),
    Column("app_id", String(255)),
    Column("side", String(255)),
    Column("connect_time", Integer),
    Column("implementation", String(255)),
    Column("version", String(64)),
)
Index("client_versions_time_idx", client_versions.c.connect_time)
Index("client_versions_appid_time_idx", client_versions.c.app_id,
      client_versions.c.connect_time)
Index("client_versions_replica_idx", client_versions.c.replica_id)


# -- address-id database -------------------------------------------------

addrid_metadata = MetaData()

address_ids = Table(
    "address_ids", addrid_metadata,
    Column("generation", Integer),
    Column("counter", Integer),
    Column("type", String(16)),
    Column("address", String(255)),
    Column("retain", Integer),
)


SCHEMAS = {
    "channel": channel_metadata,
    "usage": usage_metadata,
    "addrid": addrid_metadata,
}

TARGET_VERSIONS = {
    "channel": 3,
    "usage": 2,
    "addrid": 1,
}
