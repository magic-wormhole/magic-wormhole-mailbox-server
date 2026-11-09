"""Test-time database backend redirection.

When ``WORMHOLE_TEST_UNIT_BACKEND_URL`` is set (to a PostgreSQL or MySQL
SQLAlchemy URL), the normal unit suite's ``:memory:`` databases are mapped
to isolated, ephemeral schemas/databases on that backend. Tests that use a
file path map that path to a stable isolated schema/database, so multiple
connections in one test still share state.

Isolation is cheap: each isolated database is created directly from the
current Core metadata (and stamped at the Alembic head) instead of running
the full migration chain. Connections use NullPool and are closed when the
owning store is collected, which keeps connection counts bounded even for
the several hundred databases a unit run creates.

This is test infrastructure only; production code is untouched.
"""

import os
import threading
import uuid
import weakref

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool

from .. import database, schema

_ADMIN_URL = os.environ.get("WORMHOLE_TEST_UNIT_BACKEND_URL")


def _close_driver(driver):
    try:
        driver.close()
    except Exception:
        pass


def install():
    if not _ADMIN_URL:
        return
    admin_url = make_url(_ADMIN_URL)
    if admin_url.get_backend_name() == "sqlite":
        return

    admin_engine = create_engine(_ADMIN_URL)
    dialect = admin_engine.dialect.name
    if dialect not in ("postgresql", "mysql", "mariadb"):
        return

    original_make_engine = database._make_engine
    original_ensure_schema = database._ensure_schema
    original_open_store = database._open_store

    lock = threading.Lock()
    by_path = {}
    isolated_engines = weakref.WeakSet()

    def new_isolation():
        name = "wm_unit_" + uuid.uuid4().hex
        with admin_engine.connect() as conn:
            if dialect == "postgresql":
                conn.execute(text(f'CREATE SCHEMA "{name}"'))
            else:
                conn.exec_driver_sql(
                    f"CREATE DATABASE `{name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
        return name

    def engine_for(name):
        if dialect == "postgresql":
            engine = create_engine(
                admin_url,
                connect_args={"options": f"-csearch_path={name}"},
                poolclass=NullPool,
            )
        else:
            engine = create_engine(admin_url.set(database=name),
                                   poolclass=NullPool,
                                   isolation_level="READ COMMITTED")
        engine._wormhole_isolated = True
        engine._wormhole_lock_suffix = name
        isolated_engines.add(engine)
        return engine

    def isolation_for(dbfile):
        if dbfile == ":memory:":
            return new_isolation()
        key = os.path.abspath(dbfile)
        with lock:
            name = by_path.get(key)
            if name is None:
                name = new_isolation()
                by_path[key] = name
            return name

    def make_engine(dbfile):
        if "://" in dbfile:
            return original_make_engine(dbfile)
        return engine_for(isolation_for(dbfile))

    def ensure_schema(engine, name, dbfile):
        if engine not in isolated_engines:
            return original_ensure_schema(engine, name, dbfile)
        head = database.MIGRATION_HEADS[name]
        if database._alembic_version(engine, name) == head:
            return
        with database._migration_lock(engine, name):
            if database._alembic_version(engine, name) == head:
                return
            schema.SCHEMAS[name].create_all(engine)
            database._stamp(engine, name, head)

    def open_store(dbfile, name, *args, **kwargs):
        store = original_open_store(dbfile, name, *args, **kwargs)
        if getattr(store.engine, "_wormhole_isolated", False):
            connection = store.connection
            # Several store wrappers can share one connection (Server,
            # AppNamespace, Mailbox), so the finalizer must live on the
            # connection rather than on any individual store.
            if "_wormhole_finalized" not in connection.info:
                driver = connection.connection.driver_connection
                connection.info["_wormhole_finalized"] = weakref.finalize(
                    connection, _close_driver, driver)
        return store

    database._make_engine = make_engine
    database._ensure_schema = ensure_schema
    database._open_store = open_store
