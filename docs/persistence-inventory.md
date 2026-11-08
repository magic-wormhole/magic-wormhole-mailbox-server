# Persistence inventory

This document records the persistence boundary found while starting the
SQLAlchemy port described in [sql-alchemy.md](sql-alchemy.md). It is the
baseline for the refactor: after step 1, protocol code must not contain SQL.

## After step 2

Schema and ordinary reads/writes now go through SQLAlchemy Core:

* `src/wormhole_mailbox_server/schema.py` defines the three databases as
  `MetaData`/`Table` objects with explicit types, foreign keys, and indexes.
* Fresh current-version databases are created from that metadata. The
  historical `db-schemas/*.sql` files are now used only to fabricate old
  versions in upgrade tests and to run the existing upgrade scripts.
* `store.py` executes Core expressions through one SQLAlchemy `Connection`
  per database. `execute()` remains as a documented escape hatch for tests;
  protocol code no longer uses it.
* `dump_db()` unwraps a store to the driver connection for `iterdump()`.

Known legacy inconsistency to resolve in the migration step:
`channel-v2.sql` (and therefore fresh Core databases) has
`addrid_generation(generation, started)`, while
`upgrade-channel-to-v2.sql` adds an unused `ends` column. Alembic should
produce the same shape as the fresh schema.

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

## Commit points / transactions (after step 3)

Each store has a re-entrant `transaction()` scope. Nested scopes (including
across store instances sharing a connection) join the outermost transaction,
which commits on success and rolls back on error. Protocol methods declare
their own scopes, so partial writes are no longer committed mid-operation.

* `Mailbox.open()` is one transaction.
* `Mailbox.add_message()` is one transaction (message insert + mailbox
  touch).
* `Mailbox.close()` commits the channel state in one transaction, then
  writes usage in a separate usage-DB transaction.
* `AppNamespace.claim_nameplate()` commits nameplate/side creation in one
  transaction, then opens the mailbox in a second transaction. A crowded
  claim intentionally commits the offending side rows before raising, so
  the channel can still be summarized as `crowded` (matching the historical
  behavior).
* `AppNamespace.release_nameplate()` updates and deletes in one channel
  transaction, then writes usage separately.
* `AppNamespace.prune()` touches listeners, reads, and deletes in one
  channel transaction; usage writes are separate per retired record.
* `ConnectionTable`/`Connection` and `AddressIDTracker` wrap each logical
  write in a transaction. Address-id allocation keeps its read+insert in
  one address-id transaction.
* Transactions are never held open across network activity.

## Ordering

* `messages` has an autoincrement `id` primary key, and replay ordering is
  explicit: `ORDER BY server_rx ASC, id ASC`. Ties on `server_rx` are
  resolved by insertion order, not by SQLite rowid.
* The channel DB target version is now 3; `upgrade-channel-to-v3.sql`
  rebuilds `messages` and copies rows in rowid order so existing deployments
  keep their old replay order.
* `test_store.py` covers same-timestamp ordering, reconnects, and concurrent
  inserts from two separate SQLite connections.

## Old commit points (before step 3)

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

## Old ordering (before step 3)

* Message replay ordering was `ORDER BY server_rx ASC` in
  `MailboxStore.get_messages()`. `server_rx` is supplied by the caller and
  is not necessarily unique, so ties were resolved by whatever order SQLite
  returned (implicit rowid order).
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
