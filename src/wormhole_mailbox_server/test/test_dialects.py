"""Optional behavioral tests against a non-SQLite database.

Set ``WORMHOLE_TEST_DATABASE_URL`` to a SQLAlchemy URL (for example
``postgresql://user:pass@localhost/wormhole_test``) to run these. They are
skipped by default so the normal suite stays SQLite-only.
"""

import base64
import os

from twisted.trial import unittest

from ..database import create_or_upgrade_channel_db
from ..server import SidedMessage, make_server


def _unique(prefix):
    return prefix + base64.b32encode(os.urandom(6)).decode("ascii").lower()


class AlternateBackend(unittest.TestCase):
    def _store(self):
        url = os.environ.get("WORMHOLE_TEST_DATABASE_URL")
        if not url:
            raise unittest.SkipTest(
                "set WORMHOLE_TEST_DATABASE_URL to test another backend")
        return create_or_upgrade_channel_db(url)

    def test_channel_roundtrip(self):
        app_id = _unique("app-")
        mailbox_id = _unique("mid-")
        store = self._store()

        store.insert_mailbox(app_id, mailbox_id, True, 0)
        store.commit()

        server = make_server(store)
        app = server.get_app(app_id)
        mailbox = app.open_mailbox(mailbox_id, "side1", 0)
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="one", server_rx=5, msg_id="m1"))
        mailbox.add_message(SidedMessage(
            side="side2", phase="p", body="two", server_rx=5, msg_id="m2"))
        mailbox.add_message(SidedMessage(
            side="side1", phase="p", body="zero", server_rx=4, msg_id="m0"))

        self.assertEqual([m.body for m in mailbox.get_messages()],
                         ["zero", "one", "two"])

        mailbox.close("side1", "happy", 10)
        mailbox.close("side2", "happy", 11)
