import os
import threading

from twisted.trial import unittest

from ..database import create_channel_db, create_or_upgrade_channel_db
from ..server import SidedMessage, make_server


class MessageOrdering(unittest.TestCase):
    def test_server_rx_then_insertion_order(self):
        server = make_server(create_channel_db(":memory:"))
        app = server.get_app("appid")
        mailbox = app.open_mailbox("mid", "side1", 0)

        # Two messages share a server_rx value; the explicit message id is
        # the tie-breaker. A later insert with an earlier server_rx must
        # still sort first.
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="b1", server_rx=5, msg_id="m1"))
        mailbox.add_message(SidedMessage(
            side="side2", phase="p", body="b2", server_rx=5, msg_id="m2"))
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="b0", server_rx=4, msg_id="m0"))
        mailbox.add_message(SidedMessage(
            side="side2", phase="p", body="b3", server_rx=5, msg_id="m3"))

        self.assertEqual([m.body for m in mailbox.get_messages()],
                         ["b0", "b1", "b2", "b3"])

    def test_ties_across_reconnect(self):
        server = make_server(create_channel_db(":memory:"))
        app = server.get_app("appid")
        mailbox = app.open_mailbox("mid", "side1", 0)
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="first", server_rx=10,
            msg_id="m1"))
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="second", server_rx=10,
            msg_id="m2"))

        # Re-opening and re-reading must preserve the same order.
        app.open_mailbox("mid", "side2", 11)
        self.assertEqual([m.body for m in mailbox.get_messages()],
                         ["first", "second"])


class ConcurrentInserts(unittest.TestCase):
    def test_separate_connections(self):
        basedir = self.mktemp()
        os.mkdir(basedir)
        fn = os.path.join(basedir, "concurrent.db")

        setup = create_channel_db(fn)
        setup.insert_mailbox("appid", "mid", True, 0)
        setup.commit()

        barrier = threading.Barrier(2)
        errors = []

        def worker(side):
            try:
                store = create_or_upgrade_channel_db(fn)
                barrier.wait()
                for i in range(20):
                    store.insert_message(
                        "appid", "mid", side, "phase",
                        "%s-%d" % (side, i), 1, "msg")
                    store.commit()
                store.connection.close()
            except Exception as e: # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(side,))
                   for side in ("side1", "side2")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

        rows = setup.get_messages("appid", "mid")
        self.assertEqual(len(rows), 40)
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 40)
