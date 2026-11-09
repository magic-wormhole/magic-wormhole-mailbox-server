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

Known legacy inconsistency, resolved in step 4: `channel-v2.sql` (and
therefore fresh Core databases) has `addrid_generation(generation, started)`,
while `upgrade-channel-to-v2.sql` adds an unused `ends` column. The v2->v3
upgrade now rebuilds `addrid_generation` without `ends`, so upgraded and
fresh databases agree.

## After step 4

* Alembic is the runtime migration mechanism, with one independent lineage
  and version table per database:
  `channel_0002` / `alembic_version_channel`,
  `usage_0002` / `alembic_version_usage`,
  `addrid_0001` / `alembic_version_addrid`. Migration scripts ship inside
  the package (`src/wormhole_mailbox_server/migrations/`).
* Fresh databases are created by Alembic. Pre-Alembic databases are
  detected by their integer `version` table, upgraded to the latest legacy
  schema (channel 3, usage 2, addrid 1) with the existing SQL scripts, then
  stamped at the corresponding initial Alembic revision. A backup copy is
  still written before a legacy upgrade.
* `_get_db()` and the `db-schemas/*.sql` files remain as a test/tooling
  path for fabricating and upgrading old databases; normal startup uses
  `create_or_upgrade_*` and Alembic.
* The engine factory accepts either a filesystem path / `:memory:` (SQLite)
  or a SQLAlchemy URL containing `://`. SQLite still gets the
  `foreign_keys` pragma and file-based atomic creation; other dialects skip
  SQLite-only checks.
* Migration execution is serialized **per database**, not per process, so
  multiple server processes can share one database safely. PostgreSQL uses
  `pg_advisory_lock`, MySQL/MariaDB use `GET_LOCK`, and SQLite uses an
  exclusive lock on `<database>.migration-lock`. Every process re-checks
  the Alembic revision after acquiring the lock, so only one performs the
  upgrade.
* Revision scripts take an explicit `Operations` object and are applied by
  a small in-package runner instead of the `alembic` CLI. This avoids
  Alembic's process-global `op` proxy, so migrations for different
  databases can run concurrently within one process.
* `test_backends.py` runs a backend-agnostic behavioral suite
  (claim/release, replay ordering, reconnect persistence, transactions,
  concurrent inserts, connections, usage, address IDs, migrations). It is
  driven by `WORMHOLE_TEST_CHANNEL_DATABASE_URL` (or
  `WORMHOLE_TEST_DATABASE_URL`), `WORMHOLE_TEST_USAGE_DATABASE_URL`, and
  `WORMHOLE_TEST_ADDRID_DATABASE_URL`, and skips without them.
* `misc/backends/test-backends.py` starts separate MySQL and PostgreSQL
  `docker compose` configurations (tmpfs-backed, so test databases are
  RAM-only and discarded with the containers), creates fresh databases, and
  runs the three unit suites in parallel first (SQLite, PostgreSQL, MySQL),
  reporting each suite's status. It then runs the three behavioral suites in
  parallel. Unit backends map each test's `:memory:` database to an isolated
  PostgreSQL schema or MySQL database (`WORMHOLE_TEST_UNIT_BACKEND_URL`);
  SQLite-specific schema/upgrade tests skip in those runs.

## Cross-process WebSocket fan-out

The internal pub/sub layer wakes WebSocket listeners in other server
processes. `pubsub/` is the transport-independent core (subscriptions,
local delivery, lifecycle, and a lazy transport registry); transport modules
(`pubsub/postgres.py`, `pubsub/redis.py`, `pubsub/kafka.py`) are imported only
when selected by the database layer.

* Messages remain durable in the channel database. `Mailbox.add_message()`
  commits the message and then publishes a small event containing the
  `app_id`, `mailbox_id`, and message id. Local listeners are notified
  synchronously; remote processes read the committed row and broadcast it to
  their own listeners.
* PostgreSQL uses `LISTEN`/`NOTIFY` on a process-scoped channel, so any
  number of server processes may share one channel database. The listener
  and publisher use the channel database's existing SQLAlchemy engine. The
  publishing process ignores its own notification.
* Redis provides an independent transport for any channel database via
  `--pubsub=redis://host:6379/0`. It requires the optional `redis` package
  (`magic-wormhole-mailbox-server[redis]`).
* Kafka provides an independent transport via
  `--pubsub=kafka://host:9092` (optionally `/topic?group=prefix`). Each
  process uses a unique consumer group so every process sees every message,
  and messages are keyed by mailbox to preserve per-mailbox order. The
  transport creates the topic if it does not exist; pass `create=false` when
  topics are provisioned externally, and `partitions=N` to choose the
  partition count. It requires the optional `confluent-kafka` package
  (`magic-wormhole-mailbox-server[kafka]`).
* Third-party transports can be added with `pubsub.register_transport(name,
  module)`; the module must expose `create_pubsub(store, spec, scope)`.
* SQLite file databases and MySQL/MariaDB have no equivalent asynchronous
  notification primitive. Without Redis or Kafka, the server acquires a
  process-lifetime lock (`<database>.server-lock` for SQLite, `GET_LOCK` for
  MySQL) and refuses to start a second process against the same database.
  In-memory SQLite is process-local already and needs no lock.
* Unsupported database dialects refuse to start rather than silently running
  replicas that cannot see each other's messages.
* `test_backends.py` verifies cross-process delivery on PostgreSQL, on
  SQLite with Redis, and on SQLite with Kafka, plus the single-process
  refusal on SQLite and MySQL.

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
  The runtime Alembic schema (`channel_0002`) adds a `replicas` registry
  (`id`, `started`, `heartbeat`, `host`, `pid`) and stamps each connection
  with its owning `replica_id`. Live sessions are the connections whose
  owning replica has a fresh heartbeat; stale replicas are reaped by TTL.
* **Usage DB** (`USAGEDB_TARGET_VERSION = 2`, optional): 
  `db-schemas/usage-v2.sql`, upgraded from v1 by
  `db-schemas/upgrade-usage-to-v2.sql`. Tables: `version`, `current`,
  `nameplates`, `mailboxes`, `client_versions`. The runtime Alembic schema
  (`usage_0002`) adds a `replica_id` to every table so multiple replicas can
  share one usage database: `current` is keyed by `replica_id`, while the
  shared event tables use an autoincrement `id` as their primary key and keep
  `replica_id` as non-key attribution metadata. A `replicas` table
  (`replica_id` primary key, `hostname`) records the OS hostname of each
  replica that opens the database.
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
* replicas: register (clearing that replica's previous connections),
  heartbeat, delete, and expire rows whose heartbeat is stale.
* connections: clear one replica's rows, insert (returning `id`) stamped
  with `replica_id`, bind to a side, update `active`, insert
  `connection_messages`, delete connection and its messages, and list live
  connections joined to fresh replicas.

`UsageStore` (usage DB): register this replica's hostname, insert
`client_versions`, insert nameplate summaries, insert mailbox summaries,
replace this replica's `current` row. Every row is stamped with the store's
persistent `replica_id`.

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
