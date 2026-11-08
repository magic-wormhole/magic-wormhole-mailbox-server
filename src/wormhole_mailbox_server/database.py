import importlib.resources
import hashlib
import os, shutil
import sqlite3
import tempfile
from contextlib import contextmanager

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt

from twisted.python import log

from .schema import TARGET_VERSIONS
from .store import AddressIDStore, MailboxStore, UsageStore, _Store


class DBError(Exception):
    pass


def get_schema(name, version):
    sql_filepath = f"db-schemas/{name}-v{version}.sql"
    path = importlib.resources.files("wormhole_mailbox_server").joinpath(sql_filepath)
    return path.read_text(encoding="utf-8")


def get_upgrader(name, new_version):
    sql_filepath = f"db-schemas/upgrade-{name}-to-v{new_version}.sql"
    path = importlib.resources.files("wormhole_mailbox_server").joinpath(sql_filepath)
    try:
        return path.read_text(encoding="utf-8")
    except OSError: # includes FileNotFoundError
        raise ValueError("no upgrader for %d" % new_version)


# Latest schema version of the pre-Alembic, integer-versioned databases.
# These are still used to fabricate and upgrade old databases.
CHANNELDB_TARGET_VERSION = TARGET_VERSIONS["channel"]
USAGEDB_TARGET_VERSION = TARGET_VERSIONS["usage"]
ADDRIDDB_TARGET_VERSION = TARGET_VERSIONS["addrid"]

_STORE_CLASSES = {
    "channel": MailboxStore,
    "usage": UsageStore,
    "addrid": AddressIDStore,
}

# Each database has its own Alembic lineage and version table.
MIGRATION_HEADS = {
    "channel": "channel_0001",
    "usage": "usage_0001",
    "addrid": "addrid_0001",
}
_INITIAL_REVISIONS = dict(MIGRATION_HEADS)
_VERSION_TABLES = {
    "channel": "alembic_version_channel",
    "usage": "alembic_version_usage",
    "addrid": "alembic_version_addrid",
}


# ---------------------------------------------------------------------------
# engines and schema creation
# ---------------------------------------------------------------------------

def _is_url(dbfile):
    return "://" in dbfile


def _make_engine(dbfile):
    """Create a SQLAlchemy engine for a file path, ``:memory:``, or URL.

    Plain paths keep the historical SQLite behavior. A value containing
    ``://`` is treated as a SQLAlchemy URL, which is how non-SQLite backends
    (PostgreSQL, MySQL) are selected.
    """
    if _is_url(dbfile):
        kwargs = {}
        if dbfile.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in dbfile:
                kwargs["poolclass"] = StaticPool
        engine = create_engine(dbfile, **kwargs)
    elif dbfile == ":memory:":
        engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_engine("sqlite:///" + os.path.abspath(dbfile),
                               connect_args={"timeout": 30})

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return engine


def _check_foreign_keys(engine):
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        problems = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise DBError(f"failed foreign key check: {problems}")


# ---------------------------------------------------------------------------
# legacy (integer-version) schema creation, used to build old databases and
# as the upgrade path for deployments created before Alembic
# ---------------------------------------------------------------------------

def _initialize_legacy_db_schema(engine, name, target_version):
    log.msg(f"populating new database with schema {name} v{target_version}")
    schema = get_schema(name, target_version)
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(schema)
        raw.driver_connection.execute(
            "INSERT INTO version (version) VALUES (?)", (target_version,))
        raw.commit()
    finally:
        raw.close()


def _get_temporary_dbfile(dbfile):
    """Get a temporary filename near the given path.
    """
    fd, name = tempfile.mkstemp(
        prefix=os.path.basename(dbfile) + ".",
        dir=os.path.dirname(dbfile)
    )
    os.close(fd)
    return name


def _atomic_create_legacy_db(dbfile, name, target_version):
    temp_dbfile = _get_temporary_dbfile(dbfile)
    try:
        engine = _make_engine(temp_dbfile)
        _initialize_legacy_db_schema(engine, name, target_version)
        engine.dispose()
        os.rename(temp_dbfile, dbfile)
    except Exception:
        if os.path.exists(temp_dbfile):
            os.remove(temp_dbfile)
        raise
    return _make_engine(dbfile)


def _legacy_version(engine):
    """Return the integer version of a pre-Alembic database, or None."""
    inspector = inspect(engine)
    if "version" not in inspector.get_table_names():
        return None
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT version FROM version").first()
    return row[0] if row else None


def _upgrade_legacy_db(engine, name, version, target_version):
    while version < target_version:
        log.msg(f" need to upgrade from {version} to {target_version}")
        try:
            upgrader = get_upgrader(name, version+1)
        except ValueError:
            log.msg(f" unable to upgrade {version} to {version + 1}")
            raise DBError("Unable to upgrade to version %s, left at %s"
                          % (version+1, version))
        log.msg(f" executing upgrader v{version}->v{version + 1}")
        raw = engine.raw_connection()
        try:
            raw.driver_connection.executescript(upgrader)
            raw.commit()
        finally:
            raw.close()
        version = version+1


def _get_db(dbfile, name, target_version):
    """Fabricate or upgrade an old, integer-versioned database.

    This is used by tests and migration tooling; normal server startup uses
    the Alembic path in ``_open_store``.
    """
    try:
        if dbfile == ":memory:":
            engine = _make_engine(dbfile)
            _initialize_legacy_db_schema(engine, name, target_version)
        elif os.path.exists(dbfile):
            engine = _make_engine(dbfile)
        else:
            engine = _atomic_create_legacy_db(dbfile, name, target_version)
        _check_foreign_keys(engine)
        version = _legacy_version(engine)
        if version is None:
            raise DBError("database has no version table")
    except DBError:
        raise
    except (OSError, sqlite3.OperationalError, sqlite3.DatabaseError,
            SQLAlchemyError) as e:
        raise DBError(f"Unable to create/open db file {dbfile}: {e}")

    if version < target_version and dbfile != ":memory:":
        backup_fn = "%s-backup-v%d" % (dbfile, version)
        log.msg(" storing backup of v%d db in %s" % (version, backup_fn))
        shutil.copy(dbfile, backup_fn)

    if version < target_version:
        _upgrade_legacy_db(engine, name, version, target_version)
        version = _legacy_version(engine)

    if version != target_version:
        raise DBError(f"Unable to handle db version {version}")

    return _STORE_CLASSES[name](engine)


# ---------------------------------------------------------------------------
# database-scoped migration locking
#
# Migrations must be serialized across processes that share a database, not
# just across threads in one process. PostgreSQL and MySQL use advisory
# locks; SQLite (which has no advisory locks) is locked through a file
# associated with the database file. In-memory SQLite databases are not
# shared between processes, so no lock is needed.
# ---------------------------------------------------------------------------

def _lock_identity(engine, name):
    database = engine.url.database or ""
    return f"wormhole_mailbox_server:{database}:{name}"


@contextmanager
def _sqlite_migration_lock(engine):
    database = engine.url.database
    if not database or database == ":memory:":
        yield
        return
    lock_path = database + ".migration-lock"
    lock_file = open(lock_path, "a+b")
    try:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            lock_file.close()


@contextmanager
def _advisory_migration_lock(engine, name, dialect):
    identity = _lock_identity(engine, name)
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    key = None
    lock_name = None
    lock_conn = engine.connect()
    try:
        if dialect == "postgresql":
            key = int.from_bytes(digest[:8], "big", signed=True)
            lock_conn.execute(text("SELECT pg_advisory_lock(:key)"),
                              {"key": key})
        else:  # mysql / mariadb
            lock_name = "wm:" + digest.hex()[:60]
            got = lock_conn.execute(
                text("SELECT GET_LOCK(:name, :timeout)"),
                {"name": lock_name, "timeout": 300}).scalar()
            if got != 1:
                raise DBError(f"timed out acquiring migration lock for {name}")
        lock_conn.commit()
        yield
    finally:
        try:
            if dialect == "postgresql" and key is not None:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"),
                                  {"key": key})
            elif lock_name is not None:
                lock_conn.execute(text("SELECT RELEASE_LOCK(:name)"),
                                  {"name": lock_name})
        finally:
            lock_conn.close()


@contextmanager
def _migration_lock(engine, name):
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with _sqlite_migration_lock(engine):
            yield
    elif dialect == "postgresql":
        with _advisory_migration_lock(engine, name, dialect):
            yield
    elif dialect in ("mysql", "mariadb"):
        with _advisory_migration_lock(engine, name, dialect):
            yield
    else:
        raise DBError(
            f"no database migration lock implemented for dialect {dialect}")


# ---------------------------------------------------------------------------
# Alembic migrations
#
# We use Alembic's revision scripts and Operations API, but apply revisions
# ourselves so the module-level ``alembic.op`` proxy (which is global to the
# process) is never involved. That makes concurrent migrations on different
# databases safe within one process.
# ---------------------------------------------------------------------------

def _script_directory():
    resource = importlib.resources.files(
        "wormhole_mailbox_server").joinpath("migrations")
    return importlib.resources.as_file(resource)


def _pending_revisions(script, head, current):
    revisions = []
    revision = script.get_revision(head)
    while revision is not None:
        if revision.revision == current:
            break
        revisions.append(revision)
        down = revision.down_revision
        revision = script.get_revision(down) if down else None
    else:
        if current is not None:
            raise DBError(
                f"current revision {current!r} is not an ancestor of {head!r}")
    revisions.reverse()
    return revisions


def _run_migrations(engine, name, head):
    with _script_directory() as script_location:
        script = ScriptDirectory(str(script_location))
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"version_table": _VERSION_TABLES[name]})
            current = context.get_current_revision()
            conn.commit()
            for revision in _pending_revisions(script, head, current):
                log.msg(f" applying {name} migration {revision.revision}")
                with conn.begin():
                    revision.module.upgrade(Operations(context))
                    context.stamp(script, revision.revision)


def _stamp(engine, name, revision):
    with _script_directory() as script_location:
        script = ScriptDirectory(str(script_location))
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"version_table": _VERSION_TABLES[name]})
            with conn.begin():
                context.stamp(script, revision)


def _alembic_version(engine, name):
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"version_table": _VERSION_TABLES[name]})
        current = context.get_current_revision()
        conn.commit()
    return current


def _ensure_schema(engine, name, dbfile):
    """Bring a database up to the current Alembic head.

    Fresh databases are created by Alembic. Databases created before
    Alembic are first upgraded through the legacy integer-versioned
    scripts, then stamped at the initial Alembic revision.
    """
    try:
        if _alembic_version(engine, name) == MIGRATION_HEADS[name]:
            return
        with _migration_lock(engine, name):
            # Re-check under the database lock; another process may have
            # completed the migration while we waited.
            if _alembic_version(engine, name) != MIGRATION_HEADS[name]:
                _migrate_schema(engine, name, dbfile)
    except DBError:
        raise
    except (OSError, sqlite3.OperationalError, sqlite3.DatabaseError,
            SQLAlchemyError) as e:
        raise DBError(f"Unable to migrate db file {dbfile}: {e}")


def _migrate_schema(engine, name, dbfile):
    if _alembic_version(engine, name) is None:
        legacy = _legacy_version(engine)
        if legacy is not None:
            target = TARGET_VERSIONS[name]
            if legacy > target:
                raise DBError(f"Unable to handle db version {legacy}")
            if legacy < target:
                if dbfile != ":memory:" and not _is_url(dbfile):
                    backup_fn = "%s-backup-v%d" % (dbfile, legacy)
                    log.msg(" storing backup of v%d db in %s"
                            % (legacy, backup_fn))
                    shutil.copy(dbfile, backup_fn)
                _upgrade_legacy_db(engine, name, legacy, target)
            log.msg(f"stamping {name} database at {_INITIAL_REVISIONS[name]}")
            _stamp(engine, name, _INITIAL_REVISIONS[name])
    _run_migrations(engine, name, MIGRATION_HEADS[name])


def _open_store(dbfile, name):
    try:
        engine = _make_engine(dbfile)
        try:
            _ensure_schema(engine, name, dbfile)
        except Exception:
            engine.dispose()
            # Leave no half-migrated database behind. The migration lock is
            # held while this runs, so no other process can be using it.
            if not (_is_url(dbfile) or dbfile == ":memory:"):
                if os.path.exists(dbfile):
                    os.remove(dbfile)
            raise
        _check_foreign_keys(engine)
    except DBError:
        raise
    except (OSError, sqlite3.OperationalError, sqlite3.DatabaseError,
            SQLAlchemyError) as e:
        raise DBError(f"Unable to create/open db file {dbfile}: {e}")
    return _STORE_CLASSES[name](engine)


def create_or_upgrade_channel_db(dbfile):
    return _open_store(dbfile, "channel")

def create_or_upgrade_usage_db(dbfile):
    if dbfile is None:
        return None
    return _open_store(dbfile, "usage")

def create_or_upgrade_addrid_db(dbfile):
    return _open_store(dbfile, "addrid")


class DBDoesntExist(Exception):
    pass

def open_existing_db(dbfile):
    assert dbfile != ":memory:"
    if not os.path.exists(dbfile):
        raise DBDoesntExist()
    try:
        engine = _make_engine(dbfile)
        inspect(engine).get_table_names()
    except (OSError, sqlite3.OperationalError, sqlite3.DatabaseError,
            SQLAlchemyError) as e:
        raise DBError(f"Unable to open db file {dbfile}: {e}")
    return MailboxStore(engine)


class DBAlreadyExists(Exception):
    pass

def create_channel_db(dbfile):
    """Create the given db file. Refuse to touch a pre-existing file.

    This is meant for use by migration tools, to create the output target"""
    if not (_is_url(dbfile) or dbfile == ":memory:") and os.path.exists(dbfile):
        raise DBAlreadyExists()
    return _open_store(dbfile, "channel")

def create_usage_db(dbfile):
    if not (_is_url(dbfile) or dbfile == ":memory:") and os.path.exists(dbfile):
        raise DBAlreadyExists()
    return _open_store(dbfile, "usage")

def create_addrid_db(dbfile):
    if not (_is_url(dbfile) or dbfile == ":memory:") and os.path.exists(dbfile):
        raise DBAlreadyExists()
    return _open_store(dbfile, "addrid")


def _driver_connection(db):
    if isinstance(db, _Store):
        db = db.connection
    if isinstance(db, Engine):
        db = db.raw_connection()
    if isinstance(db, Connection):
        db = db.connection
    return getattr(db, "driver_connection", db)


def dump_db(db):
    driver = _driver_connection(db)
    return "".join(driver.iterdump())
