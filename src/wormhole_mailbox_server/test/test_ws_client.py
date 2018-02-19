from __future__ import print_function, unicode_literals
import json
from twisted.trial import unittest
from twisted.internet.defer import inlineCallbacks
from .ws_client import WSClient

class WSClientSync(unittest.TestCase):
    # make sure my 'sync' method actually works

    @inlineCallbacks
    def test_sync(self):
        sent = []
        c = WSClient()
        def _send(mtype, **kwargs):
            sent.append( (mtype, kwargs) )
        c.send = _send
        def add(mtype, **kwargs):
            kwargs["type"] = mtype
            c.onMessage(json.dumps(kwargs).encode("utf-8"), False)
        # no queued messages
        d = c.sync()
        self.assertEqual(sent, [("ping", {"ping": 0})])
        self.assertNoResult(d)
        add("pong", pong=0)
        yield d
        self.assertEqual(c.events, [])

        # one,two,ping,pong
        add("one")
        add("two", two=2)
        d = c.sync()
        add("pong", pong=1)
        yield d
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "one")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "two")
        self.assertEqual(c.events, [])

        # one,ping,two,pong
        add("one")
        d = c.sync()
        add("two", two=2)
        add("pong", pong=2)
        yield d
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "one")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "two")
        self.assertEqual(c.events, [])

        # ping,one,two,pong
        d = c.sync()
        add("one")
        add("two", two=2)
        add("pong", pong=3)
        yield d
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "one")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "two")
        self.assertEqual(c.events, [])

