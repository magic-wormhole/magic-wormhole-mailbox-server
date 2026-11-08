# Persistence inventory

This document records the persistence boundary found while starting the
SQLAlchemy port described in [sql-alchemy.md](sql-alchemy.md). It is the
baseline for the refactor: after step 1, protocol code must not contain SQL.

## Before step 1

All database access lived in the Twisted/protocol modules:

| Module | Role |
| --- | --- |
| `src/wormhole_mailbox_server/database.py` | Opens SQLite connections, loads/upgrades schema files, `PRAGMA` setup, `dump_db`. |
| `src/wormhole_mailbox_server/server.py` | `Mailbox`, `AppNamespace`, `Server` execute SQL for messages, mailboxes, nameplates, usage rows, and stats. |
| `src/wormhole_mailbox_server/address_id.py` | Reads/writes `addrid_generation` (channel DB) and `address_ids` (address-id DB). |
| `src/wormhole_mailbox_server/connections.py` | Writes `connections` and `connection_messages`. |
| `src/wormhole_mailbox_server/server_tap.py` | Creates/upgrades the channel, usage, and address-id databases. |
| `src/wormhole_mailbox_server/test/*` | Direct SQL assertions against in-memory SQLite databases. |

There is no ORM, no migration framework, and no transaction abstraction.
Each connection is a `sqlite3.Connection` with `row_factory` returning
`dict` rows.

## Databases and schema files

* **Channel DB** (`CHANNELDB_TARGET_VERSION = 2`, default `relay.sqlite`):
  `db-schemas/channel-v2.sql`, upgraded from v1 by
  `db-schemas/upgrade-channel-to-v2.sql`. Tables: `version`,
  `nameplates`, `nameplate_sides`, `mailboxes`, `mailbox_sides`,
  `messages`, `addrid_generation`, `connections`, `connection_messages`.
* **Usage DB** (`USAGEDB_TARGET_VERSION = 2`, optional): 
  `db-schemas/usage-v2.sql`, upgraded from v1 by
  `db-schemas/upgrade-usage-to-v2.sql`. Tables: `version`, `current`,
  `nameplates`, `mailboxes`, `client_versions`.
* **Address-id DB** (`ADDRIDDB_TARGET_VERSION = 1`, optional):
  `db-schemas/addrid-v1.sql`. Tables: `version`, `address_ids`.

SQLite-specific details to account for in later steps:

* `INTEGER PRIMARY KEY AUTOINCREMENT` on `nameplates.id` and
  `connections.id`; callers rely on `cursor.lastrowid`.
* `INSERT OR IGNORE` is not used today, but insert-then-check patterns
  (`SELECT` before `INSERT`) are common and are race-prone.
* `PRAGMA foreign_keys = ON` and `PRAGMA foreign_key_check` in
  `database.py`.
* `executescript()` for schema creation/upgrades, and `iterdump()` in
  `dump_db()`.
* SQLite's dynamic typing: schemas use `VARCHAR`/`BOOLEAN` but values are
  stored with type affinity. The ORM port must add explicit types.
* Foreign keys are declared but not indexed; `nameplate_sides` and
  `mailbox_sides` rely on cascading deletes performed manually in code.

## Logical operations (now in `store.py`)

`MailboxStore` (channel DB):

* nameplates: lookup by `(app_id, name)`, list names, insert (returning
  `id`), delete by id/mailbox, nameplate-side lookup/insert/claim
  flag/delete.
* mailboxes: lookup by `(app_id, id)` and by `id`, list by app, insert,
  touch `updated`, delete.
* mailbox sides: lookup, list, insert, close (`opened=False`, `mood`),
  delete by mailbox.
* messages: list by `(app_id, mailbox_id)` ordered by `server_rx ASC`,
  insert, delete by mailbox.
* app discovery: `SELECT DISTINCT app_id` over `nameplates`, `mailboxes`,
  `messages`.
* address-id generation: read the single row, replace it.
* connections: clear all, insert (returning `id`), bind to a side,
  update `active`, insert `connection_messages`, delete connection and its
  messages.

`UsageStore` (usage DB): insert `client_versions`, insert nameplate
summaries, insert mailbox summaries, replace the single `current` row.

`AddressIDStore` (address-id DB): clear, lookup by `(type, address)`,
max counter per generation, insert, lookup by `(generation, counter)`.

## Commit points / transactions (current behavior)

This is intentionally unchanged in step 1 and is the main thing to tighten
in step 3.

* `Mailbox.open()` commits after inserting the side and touching the
  mailbox.
* `Mailbox.add_message()` inserts the message, touches the mailbox, and
  commits in one short write.
* `Mailbox.close()` commits the side update, then separately deletes the
  mailbox graph and (optionally) writes usage, then commits again.
* `AppNamespace.claim_nameplate()` commits nameplate/side rows, then calls
  `open_mailbox()` which commits mailbox/side rows.
* `AppNamespace.release_nameplate()` commits the claim flag, then separately
  deletes an unused nameplate and writes usage.
* `AppNamespace.prune()` touches listener mailboxes, commits so the reads
  see those updates, then deletes and commits once at the end.
* `ConnectionTable`/`Connection` commit after each logical write.
* `AddressIDTracker.check_generation()` commits the channel generation and
  the address-id clear separately; `get_id()` commits the new counter.

## Ordering

* Message replay ordering is explicit: `ORDER BY server_rx ASC` in
  `MailboxStore.get_messages()`. `server_rx` is supplied by the caller and
  is not necessarily unique; ties are currently resolved by whatever order
  SQLite returns. Step 3 should add a stable tie-breaker (e.g. an
  autoincrement message id) without changing observable ordering for
  existing data.
* Mailbox and nameplate side ordering is only used for summaries, where
  `added` timestamps are sorted in Python.

## SQLite hooks in tests

Tests create raw connections with `create_channel_db()`,
`create_usage_db()`, and `create_addrid_db()` and read results with
`connection.execute()`. After step 1 they use
`store.connection` as an explicit escape hatch. Later steps should move
assertions to store read methods and run the same suite against Postgres
and MySQL.

## Rollout

1. Extract the storage layer (this commit); behavior unchanged, SQLite only.
2. Define the schema with SQLAlchemy Core and run queries through Core while
   still using SQLite.
3. Make each logical operation transactional and make message ordering
   explicit.
4. Add Alembic migrations, keep SQLite deployments upgradable, and enable
   PostgreSQL/MySQL behind configuration, running the behavioral suite
   against all three.
