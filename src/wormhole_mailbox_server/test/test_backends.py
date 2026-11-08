"""Backend-agnostic behavioral tests.

These run against whatever databases the environment points at, so the same
suite can be executed against SQLite, MySQL, and PostgreSQL. The wrapper in
``misc/backends/test-backends.py`` starts the servers and sets:

* ``WORMHOLE_TEST_CHANNEL_DATABASE_URL`` (or the older
  ``WORMHOLE_TEST_DATABASE_URL``)
* ``WORMHOLE_TEST_USAGE_DATABASE_URL``
* ``WORMHOLE_TEST_ADDRID_DATABASE_URL``

Without those variables the tests skip, which keeps the normal SQLite unit
suite dependency-free.
"""

import base64
import os
import random
import threading

from sqlalchemy import inspect, select
from twisted.trial import unittest

from .. import schema
from ..address_id import AddressIDTracker
from ..connections import ConnectionTable
from ..database import (MIGRATION_HEADS, create_or_upgrade_addrid_db,
                        create_or_upgrade_channel_db,
                        create_or_upgrade_usage_db, _alembic_version)
from ..server import SidedMessage, make_server


def _url(kind):
    value = os.environ.get(
        "WORMHOLE_TEST_%s_DATABASE_URL" % kind.upper())
    if value is None and kind == "channel":
        value = os.environ.get("WORMHOLE_TEST_DATABASE_URL")
    return value


def _require_url(kind):
    value = _url(kind)
    if not value:
        raise unittest.SkipTest(
            "set WORMHOLE_TEST_%s_DATABASE_URL to run backend tests"
            % kind.upper())
    return value


def _unique(prefix):
    return prefix + base64.b32encode(os.urandom(8)).decode("ascii").lower()


def _rows(store, table, *where):
    result = store.connection.execute(select(table).where(*where))
    return [dict(row) for row in result.mappings().all()]


class ChannelBehavior(unittest.TestCase):
    def setUp(self):
        self.store = create_or_upgrade_channel_db(_require_url("channel"))
        self.app_id = _unique("app-")
        self.server = make_server(self.store)
        self.app = self.server.get_app(self.app_id)

    def _nameplate_id(self):
        return str(random.randrange(10**8, 10**9))

    def test_claim_send_replay_and_close(self):
        name = self._nameplate_id()
        mailbox_id = self.app.claim_nameplate(name, "side1", 0)
        mailbox = self.app.open_mailbox(mailbox_id, "side1", 0)
        self.app.open_mailbox(mailbox_id, "side2", 1)

        # Same server_rx ties must preserve insertion order; an earlier
        # server_rx inserted later must sort first.
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="one", server_rx=5, msg_id="m1"))
        mailbox.add_message(SidedMessage(
            side="side2", phase="p", body="two", server_rx=5, msg_id="m2"))
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="zero", server_rx=4, msg_id="m0"))
        self.assertEqual([message.body for message in mailbox.get_messages()],
                         ["zero", "one", "two"])

        # Clients release their nameplate claims before closing the mailbox.
        self.app.release_nameplate(name, "side1", 9)
        self.app.release_nameplate(name, "side2", 9)
        self.assertIsNone(self.store.get_nameplate(self.app_id, name))

        mailbox.close("side1", "happy", 10)
        self.assertIsNotNone(self.store.get_mailbox(self.app_id, mailbox_id))
        mailbox.close("side2", "happy", 11)

        self.assertIsNone(self.store.get_mailbox(self.app_id, mailbox_id))
        self.assertIsNone(self.store.get_nameplate(self.app_id, name))
        self.assertEqual(self.store.get_messages(self.app_id, mailbox_id), [])

    def test_session_survives_reconnect(self):
        name = self._nameplate_id()
        mailbox_id = self.app.claim_nameplate(name, "side1", 0)
        mailbox = self.app.open_mailbox(mailbox_id, "side1", 0)
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="persisted", server_rx=5,
            msg_id="m1"))

        # A second store/server against the same database represents another
        # process or a client reconnecting after this one went away.
        other_store = create_or_upgrade_channel_db(_url("channel"))
        other_server = make_server(other_store)
        other_app = other_server.get_app(self.app_id)

        self.assertEqual(other_app.get_nameplate_ids(), {name})
        reopened_id = other_app.claim_nameplate(name, "side2", 10)
        self.assertEqual(reopened_id, mailbox_id)
        reopened = other_app.open_mailbox(reopened_id, "side2", 10)
        self.assertEqual([message.body for message in
                          reopened.get_messages()], ["persisted"])

        other_app.release_nameplate(name, "side1", 20)
        other_app.release_nameplate(name, "side2", 20)
        reopened.close("side1", "happy", 21)
        reopened.close("side2", "happy", 22)
        self.assertIsNone(other_store.get_mailbox(self.app_id, mailbox_id))

    def test_transaction_rolls_back(self):
        mailbox_id = _unique("mid-")

        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            with self.store.transaction():
                self.store.insert_mailbox(
                    self.app_id, mailbox_id, False, 0)
                self.store.insert_message(
                    self.app_id, mailbox_id, "side", "p", "body", 1, "msg")
                raise Boom

        self.assertIsNone(self.store.get_mailbox(self.app_id, mailbox_id))
        self.assertEqual(
            self.store.get_messages(self.app_id, mailbox_id), [])

    def test_concurrent_inserts(self):
        mailbox_id = _unique("mid-")
        self.store.insert_mailbox(self.app_id, mailbox_id, False, 0)
        self.store.commit()

        url = _url("channel")
        barrier = threading.Barrier(2, timeout=30)
        errors = []

        def worker(side):
            try:
                store = create_or_upgrade_channel_db(url)
                barrier.wait()
                for i in range(15):
                    store.insert_message(
                        self.app_id, mailbox_id, side, "phase",
                        "%s-%d" % (side, i), 7, "msg")
                    store.commit()
                store.connection.close()
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(side,))
                   for side in ("side1", "side2")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)

        self.assertEqual([thread for thread in threads if thread.is_alive()],
                         [])
        self.assertEqual(errors, [])
        rows = self.store.get_messages(self.app_id, mailbox_id)
        self.assertEqual(len(rows), 30)
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 30)

    def test_migration_is_idempotent(self):
        again = create_or_upgrade_channel_db(_url("channel"))
        self.assertEqual(_alembic_version(again.engine, "channel"),
                         MIGRATION_HEADS["channel"])

    def test_connections(self):
        table = ConnectionTable(self.store)
        table.clear()

        connection = table.established((1, 2), 10)
        connection.bound("side", ("impl", "1.2"))
        connection.add_message(11, "bind")

        rows = _rows(self.store, schema.connections,
                     schema.connections.c.id == connection._id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["side"], "side")
        self.assertEqual(rows[0]["active"], 11)
        self.assertEqual(rows[0]["connected"], 10)

        messages = _rows(self.store, schema.connection_messages,
                         schema.connection_messages.c.id == connection._id)
        self.assertEqual([(row["name"], row["when"]) for row in messages],
                         [("bind", 11)])

        connection.lost()
        self.assertEqual(_rows(self.store, schema.connections), [])
        self.assertEqual(_rows(self.store, schema.connection_messages), [])

    def test_address_id_generation(self):
        addrid_url = _url("addrid")
        if not addrid_url:
            raise unittest.SkipTest(
                "set WORMHOLE_TEST_ADDRID_DATABASE_URL to run this test")
        addrid_store = create_or_upgrade_addrid_db(addrid_url)
        tracker = AddressIDTracker(self.store, addrid_store)

        tracker.check_generation(1000, 100, force=True)
        first = tracker.get_id("ipv4", "1.2.3.4")
        self.assertEqual(tracker.get_id("ipv4", "1.2.3.4"), first)
        second = tracker.get_id("ipv6", "::1")
        self.assertNotEqual(first, second)
        self.assertEqual(tracker.get_address(first), ("ipv4", "1.2.3.4"))
        self.assertEqual(tracker.get_address(second), ("ipv6", "::1"))

        # A new generation clears the address table.
        tracker.check_generation(1200, 100, force=True)
        self.assertIsNone(tracker.get_address(first))
        self.assertNotEqual(tracker.get_id("ipv4", "1.2.3.4"), first)


class UsageBehavior(unittest.TestCase):
    def setUp(self):
        self.store = create_or_upgrade_usage_db(_require_url("usage"))
        self.app_id = _unique("usage-")

    def test_records_usage_rows(self):
        with self.store.transaction():
            self.store.insert_client_version(
                self.app_id, "side", 10, "python", "1.0")
            self.store.insert_nameplate_usage(
                self.app_id, 10, 5, 2, "happy")
            self.store.insert_mailbox_usage(
                self.app_id, True, 10, 5, 2, "happy")
            self.store.insert_mailbox_usage(
                self.app_id, False, 20, 6, None, "lonely")
            self.store.replace_current(100, 101, 60, 3)

        versions = _rows(self.store, schema.client_versions,
                         schema.client_versions.c.app_id == self.app_id)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["implementation"], "python")

        nameplates = _rows(self.store, schema.usage_nameplates,
                           schema.usage_nameplates.c.app_id == self.app_id)
        self.assertEqual([row["result"] for row in nameplates], ["happy"])

        mailboxes = _rows(self.store, schema.usage_mailboxes,
                          schema.usage_mailboxes.c.app_id == self.app_id)
        self.assertEqual(sorted(row["result"] for row in mailboxes),
                         ["happy", "lonely"])

        current = _rows(self.store, schema.current)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["connections_websocket"], 3)


class MigrationBehavior(unittest.TestCase):
    def test_fresh_database_is_at_head(self):
        store = create_or_upgrade_channel_db(_require_url("channel"))
        self.assertEqual(_alembic_version(store.engine, "channel"),
                         MIGRATION_HEADS["channel"])
        tables = inspect(store.engine).get_table_names()
        self.assertIn("messages", tables)
        self.assertIn("mailboxes", tables)
