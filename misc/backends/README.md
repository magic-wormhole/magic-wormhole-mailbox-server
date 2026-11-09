# Cross-backend test runner

`test-backends.py` runs the behavioral suite against SQLite, MySQL,
PostgreSQL, Redis, and Kafka in parallel.

```sh
cd brokers/magic-wormhole-mailbox-server
.venv/bin/python misc/backends/test-backends.py
```

What it does:

1. Starts PostgreSQL, MySQL, Redis, and Kafka with independent
   `docker compose` configurations (`docker-compose.postgres.yml`,
   `docker-compose.mysql.yml`, `docker-compose.redis.yml`,
   `docker-compose.kafka.yml`).
2. Creates fresh channel, usage, and address-id databases for each backend
   using a unique run id, so repeated runs never reuse state.
3. Runs the unit suites in parallel first:
   - `sqlite-unit`: the full existing `twisted.trial` suite (SQLite),
     executed with `trial -j <workers>` so the unit tests themselves run in
     parallel.
   - `postgres-unit`, `mysql-unit`: the same unit suite, with each test's
     `:memory:` database mapped to an isolated PostgreSQL schema or MySQL
     database.
   It prints a per-suite PASSED/FAILED status after this phase.
4. Then runs the behavioral suites in parallel:
   - `sqlite-behavior`: `test_backends` against temporary SQLite files.
   - `postgres-behavior`: `test_backends` against PostgreSQL.
   - `mysql-behavior`: `test_backends` against MySQL.
   - `redis-behavior`: `test_backends` against SQLite with Redis pub/sub.
   - `kafka-behavior`: `test_backends` against SQLite with Kafka pub/sub.
   It prints their statuses too.
5. Tears the containers and databases down afterwards.

The behavioral suite (`wormhole_mailbox_server.test.test_backends`) covers
nameplate claim/release, message replay ordering, transaction rollback,
concurrent message inserts, connection bookkeeping, usage rows,
address-id generations, migration idempotency, and cross-process WebSocket
fan-out. PostgreSQL is tested with two servers sharing the same channel
database via `LISTEN`/`NOTIFY`; the `redis-behavior` and `kafka-behavior`
jobs use SQLite channel databases with Redis or Kafka as the pub/sub
transport. SQLite and MySQL also verify that a second process is refused
when no cross-process pub/sub backend is configured.

Requirements:

- Docker with Compose v2 (or `docker-compose`).
- The project virtualenv with the `dev` extras installed (includes
  `psycopg`, `pymysql`, `redis`, and `confluent-kafka`).

The database containers use `tmpfs` for their data directories, so all
test databases are RAM-backed and discarded with the container. PostgreSQL
runs with `max_connections=500`; MySQL with `max_connections=1000`.

For the unit jobs, each test's `:memory:` database is mapped to an isolated
schema (PostgreSQL) or database (MySQL) created directly from the current
Core metadata and stamped at the Alembic head. Connections use `NullPool`
and are closed when their SQLAlchemy connection is collected, keeping the
connection count bounded across the hundreds of isolated databases a full
unit run creates.

These isolated schemas/databases are intentionally not dropped at process
exit (that would block on open transactions). The runner assumes a
throwaway, tmpfs-backed database instance and discards everything by
removing the container.

Ports default to `55432` for PostgreSQL, `53306` for MySQL, `56379` for
Redis, and `59092` for Kafka and can be overridden with
`WORMHOLE_POSTGRES_PORT`, `WORMHOLE_MYSQL_PORT`, `WORMHOLE_REDIS_PORT`, and
`WORMHOLE_KAFKA_PORT`.

Useful flags:

- `--no-sqlite` — only run the containerized backends.
- `--unit-jobs N` — number of parallel trial workers for the SQLite unit
  suite (`auto` by default, `1` disables parallelism).
- `--keep` — leave the containers running for debugging.
- `--keep-temp` — keep the temporary SQLite databases.

You can also run the behavioral suite directly against any URL:

```sh
WORMHOLE_TEST_CHANNEL_DATABASE_URL=postgresql+psycopg://... \
WORMHOLE_TEST_USAGE_DATABASE_URL=postgresql+psycopg://... \
WORMHOLE_TEST_ADDRID_DATABASE_URL=postgresql+psycopg://... \
.venv/bin/python -m twisted.trial wormhole_mailbox_server.test.test_backends
```
