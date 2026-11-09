import os
from sqlalchemy import inspect
from twisted.python import filepath
from twisted.trial import unittest
from .. import database
from ..database import (CHANNELDB_TARGET_VERSION, USAGEDB_TARGET_VERSION,
                        _get_db, dump_db, DBError)

if os.environ.get("WORMHOLE_TEST_UNIT_BACKEND_URL"):
    _SQLITE_ONLY_SKIP = (
        "database schema/upgrade tests use SQLite-specific legacy files")
else:
    _SQLITE_ONLY_SKIP = None


class SQLiteOnly(unittest.TestCase):
    skip = _SQLITE_ONLY_SKIP


def schema_signature(db):
    """Return a dialect-independent description of a database's schema."""
    inspector = inspect(db.engine)
    signature = {}
    for table in sorted(inspector.get_table_names()):
        signature[table] = {
            "columns": [
                (column["name"], str(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            ],
            "primary_key": tuple(
                inspector.get_pk_constraint(table)["constrained_columns"]),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), index["unique"])
                for index in inspector.get_indexes(table)
            ),
            "foreign_keys": sorted(
                (tuple(fk["constrained_columns"]),
                 fk["referred_table"],
                 tuple(fk["referred_columns"]))
                for fk in inspector.get_foreign_keys(table)
            ),
        }
    return signature

def schema_shape(db):
    """Return table/column/index names, ignoring legacy type/nullability
    differences between the historical SQL DDL and Core metadata."""
    signature = schema_signature(db)
    return {
        table: {
            "columns": [column[0] for column in info["columns"]],
            "primary_key": info["primary_key"],
            "indexes": [(name, columns) for name, columns, unique
                        in info["indexes"]],
        }
        for table, info in signature.items()
    }


class EngineOptions(unittest.TestCase):
    def test_mysql_uses_read_committed(self):
        # A MySQL store keeps one long-lived connection.  The default
        # REPEATABLE READ snapshot would hide rows committed by another
        # replica, breaking Redis/Kafka fan-out.
        engine = database._make_engine(
            "mysql+pymysql://user:pass@127.0.0.1/db")
        try:
            self.assertEqual(
                engine.dialect._on_connect_isolation_level,
                "READ COMMITTED")
        finally:
            engine.dispose()

    def test_sqlite_keeps_default_isolation(self):
        engine = database._make_engine("sqlite://")
        try:
            self.assertIsNone(
                engine.dialect._on_connect_isolation_level)
        finally:
            engine.dispose()


class Get(SQLiteOnly):
    def test_create_default(self):
        db_url = ":memory:"
        db = _get_db(db_url, "channel", CHANNELDB_TARGET_VERSION)
        rows = db.execute("SELECT * FROM version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], CHANNELDB_TARGET_VERSION)

    def test_open_existing_file(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "normal.db")
        db = _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        rows = db.execute("SELECT * FROM version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], CHANNELDB_TARGET_VERSION)
        db2 = _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        rows = db2.execute("SELECT * FROM version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], CHANNELDB_TARGET_VERSION)

    def test_open_bad_version(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "old.db")
        db = _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        db.execute("UPDATE version SET version=999")
        db.commit()

        with self.assertRaises(DBError) as e:
            _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        self.assertIn("Unable to handle db version 999", str(e.exception))

    def test_open_corrupt(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "corrupt.db")
        with open(fn, "wb") as f:
            f.write(b"I am not a database")
        with self.assertRaises(DBError) as e:
            _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        self.assertIn("not a database", str(e.exception))

    def test_failed_create_allows_subsequent_create(self):
        patch = self.patch(database, "get_schema", lambda version: b"this is a broken schema")
        dbfile = filepath.FilePath(self.mktemp())
        self.assertRaises(Exception, lambda: _get_db(dbfile.path))
        patch.restore()
        _get_db(dbfile.path, "channel", CHANNELDB_TARGET_VERSION)

    def test_channel_upgrade_adds_message_ids(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "channel.db")

        # Build a v2 database with messages, including ties on server_rx.
        db = _get_db(fn, "channel", 2)
        db.execute("INSERT INTO `mailboxes`"
                   " (`app_id`, `id`, `for_nameplate`, `updated`)"
                   " VALUES(?,?,?,?)", ("appid", "mid", True, 0))
        for body, rx in (("a", 5), ("b", 5), ("c", 4)):
            db.execute("INSERT INTO `messages`"
                       " (`app_id`, `mailbox_id`, `side`, `phase`, `body`,"
                       "  `server_rx`, `msg_id`)"
                       " VALUES(?,?,?,?,?,?,?)",
                       ("appid", "mid", "side", "p", body, rx, "m"))
        db.commit()
        del db

        upgraded = _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        rows = upgraded.get_messages("appid", "mid")
        self.assertEqual([row["body"] for row in rows], ["c", "a", "b"])
        # Within a shared server_rx, the explicit id is the tie-breaker.
        ties = [row["id"] for row in rows if row["server_rx"] == 5]
        self.assertEqual(ties, sorted(ties))
        self.assertEqual(sorted(row["id"] for row in rows), [1, 2, 3])

        fresh = _get_db(":memory:", "channel", CHANNELDB_TARGET_VERSION)
        self.assertEqual(schema_shape(fresh), schema_shape(upgraded))

    def test_channel_upgrade_from_v1_drops_unused_column(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "channel-v1.db")

        db = _get_db(fn, "channel", 1)
        db.execute("INSERT INTO `mailboxes`"
                   " (`app_id`, `id`, `for_nameplate`, `updated`)"
                   " VALUES(?,?,?,?)", ("appid", "mid", True, 0))
        db.execute("INSERT INTO `messages`"
                   " (`app_id`, `mailbox_id`, `side`, `phase`, `body`,"
                   "  `server_rx`, `msg_id`)"
                   " VALUES(?,?,?,?,?,?,?)",
                   ("appid", "mid", "side", "p", "body", 5, "m"))
        db.commit()
        del db

        upgraded = _get_db(fn, "channel", CHANNELDB_TARGET_VERSION)
        columns = [column["name"] for column in
                   inspect(upgraded.engine).get_columns("addrid_generation")]
        self.assertEqual(columns, ["generation", "started"])
        self.assertEqual([row["body"] for row in
                          upgraded.get_messages("appid", "mid")], ["body"])

        fresh = _get_db(":memory:", "channel", CHANNELDB_TARGET_VERSION)
        self.assertEqual(schema_shape(fresh), schema_shape(upgraded))

    def test_upgrade(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "upgrade.db")
        self.assertNotEqual(USAGEDB_TARGET_VERSION, 1)

        # create an old-version DB in a file
        db = _get_db(fn, "usage", 1)
        rows = db.execute("SELECT * FROM version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], 1)
        del db

        # then upgrade the file to the latest version
        dbA = _get_db(fn, "usage", USAGEDB_TARGET_VERSION)
        rows = dbA.execute("SELECT * FROM version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], USAGEDB_TARGET_VERSION)
        dbA_schema = schema_signature(dbA)
        dbA_text = dump_db(dbA)
        del dbA

        # make sure the upgrades got committed to disk
        dbB = _get_db(fn, "usage", USAGEDB_TARGET_VERSION)
        dbB_text = dump_db(dbB)
        self.assertEqual(schema_signature(dbB), dbA_schema)
        del dbB
        self.assertEqual(dbA_text, dbB_text)

        # The upgraded schema should be equivalent to that of a new DB.
        latest_db = _get_db(":memory:", "usage", USAGEDB_TARGET_VERSION)
        with open("up.sql","w") as f: f.write(dbA_text)
        with open("new.sql","w") as f: f.write(dump_db(latest_db))
        # debug with "diff -u _trial_temp/up.sql _trial_temp/new.sql"
        self.assertEqual(schema_signature(latest_db), dbA_schema)

    def test_upgrade_fails(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "upgrade.db")
        self.assertNotEqual(USAGEDB_TARGET_VERSION, 1)

        # create an old-version DB in a file
        db = _get_db(fn, "usage", 1)
        rows = db.execute("SELECT * FROM version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], 1)
        del db

        # then upgrade the file to a too-new version, for which we have no
        # upgrader
        with self.assertRaises(DBError):
            _get_db(fn, "usage", USAGEDB_TARGET_VERSION+1)

class Alembic(SQLiteOnly):
    def test_fresh_database_is_stamped(self):
        db = database.create_channel_db(":memory:")
        self.assertEqual(database._alembic_version(db.engine, "channel"),
                         "channel_0001")
        tables = inspect(db.engine).get_table_names()
        self.assertIn("messages", tables)
        self.assertNotIn("version", tables)

    def test_legacy_channel_upgrade_is_stamped(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "legacy-channel.db")

        legacy = _get_db(fn, "channel", 2)
        legacy.execute("INSERT INTO `mailboxes`"
                       " (`app_id`, `id`, `for_nameplate`, `updated`)"
                       " VALUES(?,?,?,?)", ("appid", "mid", True, 0))
        legacy.execute("INSERT INTO `messages`"
                       " (`app_id`, `mailbox_id`, `side`, `phase`, `body`,"
                       "  `server_rx`, `msg_id`)"
                       " VALUES(?,?,?,?,?,?,?)",
                       ("appid", "mid", "side", "p", "body", 5, "m"))
        legacy.commit()
        del legacy

        db = database.create_or_upgrade_channel_db(fn)
        self.assertEqual(database._alembic_version(db.engine, "channel"),
                         "channel_0001")
        self.assertEqual([row["body"] for row in
                          db.get_messages("appid", "mid")], ["body"])
        # Re-opening runs the migration path again without changing state.
        db2 = database.create_or_upgrade_channel_db(fn)
        self.assertEqual([row["body"] for row in
                          db2.get_messages("appid", "mid")], ["body"])

    def test_legacy_usage_upgrade_is_stamped(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "legacy-usage.db")

        legacy = _get_db(fn, "usage", 1)
        legacy.execute("INSERT INTO `nameplates`"
                       " (`app_id`, `started`, `waiting_time`,"
                       "  `total_time`, `result`)"
                       " VALUES(?,?,?,?,?)",
                       ("appid", 1, 1, 2, "happy"))
        legacy.commit()
        del legacy

        db = database.create_or_upgrade_usage_db(fn)
        self.assertEqual(database._alembic_version(db.engine, "usage"),
                         "usage_0001")
        rows = db.execute("SELECT * FROM `nameplates`").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], "happy")

    def test_corrupt_database(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "corrupt.db")
        with open(fn, "wb") as f:
            f.write(b"I am not a database")
        with self.assertRaises(DBError):
            database.create_or_upgrade_channel_db(fn)


class CreateChannel(SQLiteOnly):
    def test_memory(self):
        db = database.create_channel_db(":memory:")
        latest_text = dump_db(db)
        self.assertIn("CREATE TABLE", latest_text)

    def test_preexisting(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "preexisting.db")
        with open(fn, "w"):
            pass
        with self.assertRaises(database.DBAlreadyExists):
            database.create_channel_db(fn)

    def test_create(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        db = database.create_channel_db(fn)
        latest_text = dump_db(db)
        self.assertIn("CREATE TABLE", latest_text)

    def test_create_or_upgrade(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        db = database.create_or_upgrade_channel_db(fn)
        latest_text = dump_db(db)
        self.assertIn("CREATE TABLE", latest_text)

class CreateUsage(SQLiteOnly):
    def test_memory(self):
        db = database.create_usage_db(":memory:")
        latest_text = dump_db(db)
        self.assertIn("CREATE TABLE", latest_text)

    def test_preexisting(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "preexisting.db")
        with open(fn, "w"):
            pass
        with self.assertRaises(database.DBAlreadyExists):
            database.create_usage_db(fn)

    def test_create(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        db = database.create_usage_db(fn)
        latest_text = dump_db(db)
        self.assertIn("CREATE TABLE", latest_text)

    def test_create_or_upgrade(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        db = database.create_or_upgrade_usage_db(fn)
        latest_text = dump_db(db)
        self.assertIn("CREATE TABLE", latest_text)

    def test_create_or_upgrade_disabled(self):
        db = database.create_or_upgrade_usage_db(None)
        self.assertIs(db, None)

class OpenChannel(SQLiteOnly):
    def test_open(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        db1 = database.create_channel_db(fn)
        latest_text = dump_db(db1)
        self.assertIn("CREATE TABLE", latest_text)
        db2 = database.open_existing_db(fn)
        self.assertIn("CREATE TABLE", dump_db(db2))

    def test_doesnt_exist(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        with self.assertRaises(database.DBDoesntExist):
            database.open_existing_db(fn)

class OpenUsage(SQLiteOnly):
    def test_open(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        db1 = database.create_usage_db(fn)
        latest_text = dump_db(db1)
        self.assertIn("CREATE TABLE", latest_text)
        db2 = database.open_existing_db(fn)
        self.assertIn("CREATE TABLE", dump_db(db2))

    def test_doesnt_exist(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "created.db")
        with self.assertRaises(database.DBDoesntExist):
            database.open_existing_db(fn)


