# Porting to SQL Alchemy

I’d treat this as a database-backend refactor, not an ORM conversion. The mailbox server’s main database is on the message-delivery path, so the key design goal is to preserve its current ordering, durability, and reconnect behavior while making the SQL portable. The project also has an optional usage database; I’d migrate that separately, since it’s operational history rather than core message state. 
GitHub

1. Find and isolate the persistence boundary. Inventory every sqlite3 connection/cursor use, schema statement, and SQLite-specific query in src/ and tests. Group those operations into a small storage layer—e.g. MailboxStore and, separately, UsageStore—so the Twisted/WebSocket protocol code doesn’t know about SQLAlchemy connections or dialects.

2. Define the schema in Core, but preserve the existing data model. Translate the current tables, constraints, and indexes into SQLAlchemy Table definitions. Don’t redesign the schema during the first pass: keeping the same logical records makes it easier to compare behavior and migrate existing SQLite deployments. Use explicit types and constraints rather than relying on SQLite’s type affinity.

3. Make each logical operation transactional. Message insert, acknowledgement/deletion, and any associated state update should happen in one transaction. Keep transactions short; never hold a database transaction open while waiting on a WebSocket or other network activity. Use SQLAlchemy Core expressions for ordinary reads and writes, with text() only for SQL that is clearer as raw text.

The especially important behavior to verify is message sequencing. The project has discussed preserving per-side message order, so don’t rely on SQLite’s implicit row ordering or assume generated IDs alone guarantee the required order. Make ordering explicit in the schema and query, and test simultaneous inserts from separate connections. 
GitHub

4. Handle concurrency and dialect differences deliberately. Identify operations that currently depend on SQLite locking or INSERT OR IGNORE/other SQLite syntax. Replace them with portable constraints and Core operations where possible; if a backend-specific upsert is needed, isolate it in one method and implement/test it per dialect. Test concurrent message creation, duplicate handling, acknowledgement, and cleanup on PostgreSQL and MySQL—not just SQLite.

5. Keep the Twisted integration synchronous only if it already is. SQLAlchemy’s standard Engine is synchronous. If database calls run on the reactor thread today, avoid increasing their latency there: use the project’s existing worker/thread pattern for blocking operations, or assess an async driver separately. Don’t introduce a new async architecture just to change SQL dialects.

6. Add migrations and retain SQLite compatibility. A fresh schema created from metadata is not a migration path for existing users. Add versioned migrations—Alembic is a natural fit with SQLAlchemy—and test upgrading a copy of a real SQLite database. Keep SQLite as a supported URL/backend and test it alongside PostgreSQL and MySQL. The current server documentation describes SQLite persistence and an optional usage DB, so preserve the existing defaults unless changing them is an intentional product decision. 
GitHub

I’d do this in small PRs: first extract the storage interface without changing SQLite behavior; then move schema and queries to Core while still running SQLite; then add migrations; finally enable PostgreSQL/MySQL and run the same behavioral test suite against all three. The highest-risk tests are ordering, duplicate/retry behavior, transactions on disconnect or crash, and concurrent writes.
