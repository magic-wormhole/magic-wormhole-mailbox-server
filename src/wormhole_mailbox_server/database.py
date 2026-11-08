import importlib.resources
import os, shutil
import sqlite3
import tempfile

from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from twisted.python import log

from .schema import SCHEMAS, TARGET_VERSIONS
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


CHANNELDB_TARGET_VERSION = TARGET_VERSIONS["channel"]
USAGEDB_TARGET_VERSION = TARGET_VERSIONS["usage"]
ADDRIDDB_TARGET_VERSION = TARGET_VERSIONS["addrid"]

_STORE_CLASSES = {
    "channel": MailboxStore,
    "usage": UsageStore,
    "addrid": AddressIDStore,
}


def _make_engine(dbfile):
    """Create a SQLAlchemy engine for the given file (or ``:memory:``)."""
    if dbfile == ":memory:":
        engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_engine("sqlite:///" + os.path.abspath(dbfile))

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    return engine


def _initialize_db_schema(engine, name, target_version=None):
    """Create the application schema.

    Current-version databases are created from SQLAlchemy Core metadata.
    Older versions (used to test upgrades) are created from the historical
    SQL schema files.
    """
    if target_version is None:
        target_version = TARGET_VERSIONS[name]
    log.msg(f"populating new database with schema {name} v{target_version}")
    if target_version == TARGET_VERSIONS[name]:
        metadata = SCHEMAS[name]
        metadata.create_all(engine)
        version_table = metadata.tables["version"]
        with engine.begin() as conn:
            conn.execute(insert(version_table).values(version=target_version))
    else:
        schema = get_schema(name, target_version)
        raw = engine.raw_connection()
        try:
            raw.driver_connection.executescript(schema)
            raw.driver_connection.execute(
                "INSERT INTO version (version) VALUES (?)", (target_version,))
            raw.commit()
        finally:
            raw.close()


def _check_foreign_keys(engine):
    with engine.connect() as conn:
        problems = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise DBError(f"failed foreign key check: {problems}")


def _get_version(engine, name):
    table = SCHEMAS[name].tables["version"]
    with engine.connect() as conn:
        return conn.execute(select(table.c.version)).scalar_one()


def _get_temporary_dbfile(dbfile):
    """Get a temporary filename near the given path.
    """
    fd, name = tempfile.mkstemp(
        prefix=os.path.basename(dbfile) + ".",
        dir=os.path.dirname(dbfile)
    )
    os.close(fd)
    return name


def _atomic_create_and_initialize_db(dbfile, name, target_version=None):
    """Create and return a new database engine, initialized with the
    application schema.

    If anything goes wrong, nothing is left at the ``dbfile`` path.
    """
    temp_dbfile = _get_temporary_dbfile(dbfile)
    try:
        engine = _make_engine(temp_dbfile)
        _initialize_db_schema(engine, name, target_version)
        engine.dispose()
        os.rename(temp_dbfile, dbfile)
    except Exception:
        if os.path.exists(temp_dbfile):
            os.remove(temp_dbfile)
        raise
    return _make_engine(dbfile)


def _upgrade_db(engine, name, version, target_version):
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
    """Open or create the given db file. The parent directory must exist.
    Returns a store bound to the database, or raises DBError.
    """
    try:
        if dbfile == ":memory:":
            engine = _make_engine(dbfile)
            _initialize_db_schema(engine, name, target_version)
        elif os.path.exists(dbfile):
            engine = _make_engine(dbfile)
        else:
            engine = _atomic_create_and_initialize_db(dbfile, name,
                                                       target_version)
        _check_foreign_keys(engine)
        version = _get_version(engine, name)
    except DBError:
        raise
    except (OSError, sqlite3.OperationalError, sqlite3.DatabaseError,
            SQLAlchemyError) as e:
        # this indicates that the file is not a compatible database format.
        # Perhaps it was created with an old version, or it might be junk.
        raise DBError(f"Unable to create/open db file {dbfile}: {e}")

    if version < target_version and dbfile != ":memory:":
        backup_fn = "%s-backup-v%d" % (dbfile, version)
        log.msg(" storing backup of v%d db in %s" % (version, backup_fn))
        shutil.copy(dbfile, backup_fn)

    if version < target_version:
        _upgrade_db(engine, name, version, target_version)
        version = _get_version(engine, name)

    if version != target_version:
        raise DBError(f"Unable to handle db version {version}")

    return _STORE_CLASSES[name](engine)


def create_or_upgrade_channel_db(dbfile):
    return _get_db(dbfile, "channel", CHANNELDB_TARGET_VERSION)

def create_or_upgrade_usage_db(dbfile):
    if dbfile is None:
        return None
    return _get_db(dbfile, "usage", USAGEDB_TARGET_VERSION)

def create_or_upgrade_addrid_db(dbfile):
    return _get_db(dbfile, "addrid", ADDRIDDB_TARGET_VERSION)


class DBDoesntExist(Exception):
    pass

def open_existing_db(dbfile):
    assert dbfile != ":memory:"
    if not os.path.exists(dbfile):
        raise DBDoesntExist()
    try:
        engine = _make_engine(dbfile)
        _check_foreign_keys(engine)
        _get_version(engine, "channel")
    except (OSError, sqlite3.OperationalError, sqlite3.DatabaseError,
            SQLAlchemyError) as e:
        raise DBError(f"Unable to open db file {dbfile}: {e}")
    return _STORE_CLASSES["channel"](engine)


class DBAlreadyExists(Exception):
    pass

def _create_db(dbfile, name):
    if dbfile == ":memory:":
        engine = _make_engine(dbfile)
        _initialize_db_schema(engine, name)
    elif os.path.exists(dbfile):
        raise DBAlreadyExists()
    else:
        engine = _atomic_create_and_initialize_db(dbfile, name)
    return _STORE_CLASSES[name](engine)

def create_channel_db(dbfile):
    """Create the given db file. Refuse to touch a pre-existing file.

    This is meant for use by migration tools, to create the output target"""
    return _create_db(dbfile, "channel")

def create_usage_db(dbfile):
    return _create_db(dbfile, "usage")

def create_addrid_db(dbfile):
    return _create_db(dbfile, "addrid")


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
