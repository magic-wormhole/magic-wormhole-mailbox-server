"""SQLAlchemy Core schema definitions for the three databases.

The logical schema is deliberately identical to the historical SQLite
schema in ``db-schemas/``: same tables, columns, constraints, and indexes.
Types are declared explicitly so the definitions are portable to other
dialects, and the autoincrementing integer keys are kept for compatibility
with existing databases.

The schema is split into three ``MetaData`` objects because the server uses
three separate databases (channel, usage, and address-id).
"""

from sqlalchemy import (Boolean, Column, ForeignKey, Index, Integer,
                        MetaData, String, Table)


def _version_table(metadata):
    return Table(
        "version", metadata,
        Column("version", Integer),
    )


# -- channel database ----------------------------------------------------

channel_metadata = MetaData()

_version = _version_table(channel_metadata)

nameplates = Table(
    "nameplates", channel_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("app_id", String),
    Column("name", String),
    Column("mailbox_id", String, ForeignKey("mailboxes.id")),
    Column("request_id", String),
)
Index("nameplates_idx", nameplates.c.app_id, nameplates.c.name)
Index("nameplates_mailbox_idx", nameplates.c.app_id, nameplates.c.mailbox_id)
Index("nameplates_request_idx", nameplates.c.app_id, nameplates.c.request_id)

mailboxes = Table(
    "mailboxes", channel_metadata,
    Column("app_id", String),
    Column("id", String, primary_key=True),
    Column("updated", Integer),
    Column("for_nameplate", Boolean),
)
Index("mailboxes_idx", mailboxes.c.app_id, mailboxes.c.id)

nameplate_sides = Table(
    "nameplate_sides", channel_metadata,
    Column("nameplates_id", Integer, ForeignKey("nameplates.id")),
    Column("claimed", Boolean),
    Column("side", String),
    Column("added", Integer),
)

mailbox_sides = Table(
    "mailbox_sides", channel_metadata,
    Column("mailbox_id", String, ForeignKey("mailboxes.id")),
    Column("opened", Boolean),
    Column("side", String),
    Column("added", Integer),
    Column("mood", String),
)

messages = Table(
    "messages", channel_metadata,
    Column("app_id", String),
    Column("mailbox_id", String),
    Column("side", String),
    Column("phase", String),
    Column("body", String),
    Column("server_rx", Integer),
    Column("msg_id", String),
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
    Column("side", String),
    Column("implementation", String),
    Column("version", String),
    Column("active", Integer),
)

connection_messages = Table(
    "connection_messages", channel_metadata,
    Column("id", Integer, ForeignKey("connections.id")),
    Column("when", Integer),
    Column("name", String),
)


# -- usage database ------------------------------------------------------

usage_metadata = MetaData()

_usage_version = _version_table(usage_metadata)

current = Table(
    "current", usage_metadata,
    Column("rebooted", Integer),
    Column("updated", Integer),
    Column("blur_time", Integer),
    Column("connections_websocket", Integer),
)

usage_nameplates = Table(
    "nameplates", usage_metadata,
    Column("app_id", String),
    Column("started", Integer),
    Column("waiting_time", Integer),
    Column("total_time", Integer),
    Column("result", String),
)
Index("nameplates_idx", usage_nameplates.c.app_id,
      usage_nameplates.c.started)

usage_mailboxes = Table(
    "mailboxes", usage_metadata,
    Column("app_id", String),
    Column("for_nameplate", Boolean),
    Column("started", Integer),
    Column("total_time", Integer),
    Column("waiting_time", Integer),
    Column("result", String),
)
Index("mailboxes_idx", usage_mailboxes.c.app_id, usage_mailboxes.c.started)
Index("mailboxes_result_idx", usage_mailboxes.c.result)

client_versions = Table(
    "client_versions", usage_metadata,
    Column("app_id", String),
    Column("side", String),
    Column("connect_time", Integer),
    Column("implementation", String),
    Column("version", String),
)
Index("client_versions_time_idx", client_versions.c.connect_time)
Index("client_versions_appid_time_idx", client_versions.c.app_id,
      client_versions.c.connect_time)


# -- address-id database -------------------------------------------------

addrid_metadata = MetaData()

_addrid_version = _version_table(addrid_metadata)

address_ids = Table(
    "address_ids", addrid_metadata,
    Column("generation", Integer),
    Column("counter", Integer),
    Column("type", String),
    Column("address", String),
    Column("retain", Integer),
)


SCHEMAS = {
    "channel": channel_metadata,
    "usage": usage_metadata,
    "addrid": addrid_metadata,
}

TARGET_VERSIONS = {
    "channel": 2,
    "usage": 2,
    "addrid": 1,
}
