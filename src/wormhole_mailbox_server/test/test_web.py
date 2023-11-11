from __future__ import print_function, unicode_literals
import io, time
from unittest import mock
import treq
from twisted.trial import unittest
from twisted.internet import defer, reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from ..web import make_web_server
from ..server import SidedMessage
from ..database import create_or_upgrade_usage_db
from .common import ServerBase, _Util
from .ws_client import WSFactory

class WebSocketProtocolOptions(unittest.TestCase):
    @mock.patch('wormhole_mailbox_server.web.WebSocketServerFactory')
    def test_set(self, fake_factory):
        make_web_server(None, False,
                        websocket_protocol_options=[ ("foo", "bar"), ],
                        )
        self.assertEqual(
            mock.call().setProtocolOptions(foo="bar"),
            fake_factory.mock_calls[1],
        )

class LogRequests(ServerBase, unittest.TestCase):
    def setUp(self):
        self._clients = []

    def tearDown(self):
        for c in self._clients:
            c.transport.loseConnection()
        return ServerBase.tearDown(self)

    @inlineCallbacks
    def make_client(self):
        f = WSFactory(self.relayurl)
        f.d = defer.Deferred()
        reactor.connectTCP("127.0.0.1", self.rdv_ws_port, f)
        c = yield f.d
        self._clients.append(c)
        returnValue(c)

    @inlineCallbacks
    def test_log_http(self):
        yield self._setup_relay(do_listen=True, web_log_requests=True)
        # check the HTTP log
        fakelog = io.BytesIO()
        self._site.logFile = fakelog
        yield treq.get("http://127.0.0.1:%d/" % self.rdv_ws_port,
                       persistent=False)
        lines = fakelog.getvalue().splitlines()
        self.assertEqual(len(lines), 1, lines)

    @inlineCallbacks
    def test_log_websocket(self):
        yield self._setup_relay(do_listen=True, web_log_requests=True)
        # now check the twisted log for websocket connect messages
        with mock.patch("wormhole_mailbox_server.server_websocket.log.msg") as l:
            c1 = yield self.make_client()
            yield c1.next_non_ack()
            # the actual message includes the TCP port number of the client
            client_port = self._clients[0].transport.getHost().port
            expected = "ws client connecting: tcp4:127.0.0.1:%d" % client_port
            self.assertEqual(l.mock_calls, [mock.call(expected)])


    @inlineCallbacks
    def test_no_log_http(self):
        yield self._setup_relay(do_listen=True, web_log_requests=False)
        # check the HTTP log
        fakelog = io.BytesIO()
        self._site.logFile = fakelog
        yield treq.get("http://127.0.0.1:%d/" % self.rdv_ws_port,
                       persistent=False)
        lines = fakelog.getvalue().splitlines()
        self.assertEqual(len(lines), 0, lines)

    @inlineCallbacks
    def test_no_log_websocket(self):
        yield self._setup_relay(do_listen=True,
                                blur_usage=60, web_log_requests=True)
        # now check the twisted log for websocket connect messages
        with mock.patch("wormhole_mailbox_server.server_websocket.log.msg") as l:
            c1 = yield self.make_client()
            yield c1.next_non_ack()
            self.assertEqual(l.mock_calls, [])


class WebSocketAPI(_Util, ServerBase, unittest.TestCase):
    @inlineCallbacks
    def setUp(self):
        self._lp = None
        self._clients = []
        self._usage_db = usage_db = create_or_upgrade_usage_db(":memory:")
        yield self._setup_relay(do_listen=True,
                                advertise_version="advertised.version",
                                usage_db=usage_db)

    def tearDown(self):
        for c in self._clients:
            c.transport.loseConnection()
        return ServerBase.tearDown(self)

    @inlineCallbacks
    def make_client(self):
        f = WSFactory(self.relayurl)
        f.d = defer.Deferred()
        reactor.connectTCP("127.0.0.1", self.rdv_ws_port, f)
        c = yield f.d
        self._clients.append(c)
        returnValue(c)

    def check_welcome(self, data):
        self.failUnlessIn("welcome", data)
        self.failUnlessEqual(data["welcome"],
                             {"current_cli_version": "advertised.version"})

    @inlineCallbacks
    def test_welcome(self):
        c1 = yield self.make_client()
        msg = yield c1.next_non_ack()
        self.check_welcome(msg)
        self.assertEqual(self._server._apps, {})

    @inlineCallbacks
    def test_bind(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()

        c1.send("bind", appid="appid") # missing side=
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "bind requires 'side'")

        c1.send("bind", side="side") # missing appid=
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "bind requires 'appid'")

        c1.send("bind", appid="appid", side="side")
        yield c1.sync()
        self.assertEqual(list(self._server._apps.keys()), ["appid"])

        c1.send("bind", appid="appid", side="side") # duplicate
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "already bound")

        c1.send_notype(other="misc") # missing 'type'
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "missing 'type'")

        c1.send("___unknown") # unknown type
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "unknown type")

        c1.send("ping") # missing 'ping'
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "ping requires 'ping'")

    @inlineCallbacks
    def test_bind_with_client_version(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()

        c1.send("bind", appid="appid", side="side",
                client_version=("python", "1.2.3"))
        yield c1.sync()
        self.assertEqual(list(self._server._apps.keys()), ["appid"])
        v = self._usage_db.execute("SELECT * FROM `client_versions`").fetchall()
        self.assertEqual(v[0]["app_id"], "appid")
        self.assertEqual(v[0]["side"], "side")
        self.assertEqual(v[0]["implementation"], "python")
        self.assertEqual(v[0]["version"], "1.2.3")

    @inlineCallbacks
    def test_bind_without_client_version(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()

        c1.send("bind", appid="appid", side="side")
        yield c1.sync()
        self.assertEqual(list(self._server._apps.keys()), ["appid"])
        v = self._usage_db.execute("SELECT * FROM `client_versions`").fetchall()
        self.assertEqual(v[0]["app_id"], "appid")
        self.assertEqual(v[0]["side"], "side")
        self.assertEqual(v[0]["implementation"], None)
        self.assertEqual(v[0]["version"], None)

    @inlineCallbacks
    def test_bind_with_client_version_extra_junk(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()

        c1.send("bind", appid="appid", side="side",
                client_version=("python", "1.2.3", "extra ignore me"))
        yield c1.sync()
        self.assertEqual(list(self._server._apps.keys()), ["appid"])
        v = self._usage_db.execute("SELECT * FROM `client_versions`").fetchall()
        self.assertEqual(v[0]["app_id"], "appid")
        self.assertEqual(v[0]["side"], "side")
        self.assertEqual(v[0]["implementation"], "python")
        self.assertEqual(v[0]["version"], "1.2.3")

    @inlineCallbacks
    def test_list(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()

        c1.send("list") # too early, must bind first
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "must bind first")

        c1.send("bind", appid="appid", side="side")
        c1.send("list")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "nameplates")
        self.assertEqual(m["nameplates"], [])

        app = self._server.get_app("appid")
        nameplate_id1 = app.allocate_nameplate("side", 0)
        app.claim_nameplate("np2", "side", 0)

        c1.send("list")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "nameplates")
        nids = set()
        for n in m["nameplates"]:
            self.assertEqual(type(n), dict)
            self.assertEqual(list(n.keys()), ["id"])
            nids.add(n["id"])
        self.assertEqual(nids, set([nameplate_id1, "np2"]))

    @inlineCallbacks
    def test_allocate(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()

        c1.send("allocate") # too early, must bind first
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "must bind first")

        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")
        c1.send("allocate")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "allocated")
        name = m["nameplate"]

        nids = app.get_nameplate_ids()
        self.assertEqual(len(nids), 1)
        self.assertEqual(name, list(nids)[0])

        c1.send("allocate")
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"],
                         "you already allocated one, don't be greedy")

        c1.send("claim", nameplate=name) # allocate+claim is ok
        yield c1.sync()
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["side"], "side")

    @inlineCallbacks
    def test_claim(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        c1.send("claim") # missing nameplate=
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "claim requires 'nameplate'")

        c1.send("claim", nameplate="np1")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "claimed")
        mailbox_id = m["mailbox"]
        self.assertEqual(type(mailbox_id), type(""))

        c1.send("claim", nameplate="np1")
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error", err)
        self.assertEqual(err["error"], "only one claim per connection")

        nids = app.get_nameplate_ids()
        self.assertEqual(len(nids), 1)
        self.assertEqual("np1", list(nids)[0])
        np_row, side_rows = self._nameplate(app, "np1")
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["side"], "side")

        # claiming a nameplate assigns a random mailbox id and creates the
        # mailbox row
        mailboxes = app._db.execute("SELECT * FROM `mailboxes`"
                                    " WHERE `app_id`='appid'").fetchall()
        self.assertEqual(len(mailboxes), 1)

    @inlineCallbacks
    def test_claim_crowded(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        app.claim_nameplate("np1", "side1", 0)
        app.claim_nameplate("np1", "side2", 0)

        # the third claim will signal crowding
        c1.send("claim", nameplate="np1")
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "crowded")

    @inlineCallbacks
    def test_release(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        app.claim_nameplate("np1", "side2", 0)

        c1.send("release") # didn't do claim first
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"],
                         "release without nameplate must follow claim")

        c1.send("claim", nameplate="np1")
        yield c1.next_non_ack()

        c1.send("release")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "released", m)

        np_row, side_rows = self._nameplate(app, "np1")
        claims = [(row["side"], row["claimed"]) for row in side_rows]
        self.assertIn(("side", False), claims)
        self.assertIn(("side2", True), claims)

        c1.send("release") # no longer claimed
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "only one release per connection")

    @inlineCallbacks
    def test_release_named(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")

        c1.send("claim", nameplate="np1")
        yield c1.next_non_ack()

        c1.send("release", nameplate="np1")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "released", m)

    @inlineCallbacks
    def test_release_named_ignored(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")

        c1.send("release", nameplate="np1") # didn't do claim first, ignored
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "released", m)

    @inlineCallbacks
    def test_release_named_mismatch(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")

        c1.send("claim", nameplate="np1")
        yield c1.next_non_ack()

        c1.send("release", nameplate="np2") # mismatching nameplate
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"],
                         "release and claim must use same nameplate")

    @inlineCallbacks
    def test_open(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        c1.send("open") # missing mailbox=
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "open requires 'mailbox'")

        mb1 = app.open_mailbox("mb1", "side2", 0)
        mb1.add_message(SidedMessage(side="side2", phase="phase",
                                     body="body", server_rx=0,
                                     msg_id="msgid"))

        c1.send("open", mailbox="mb1")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "message")
        self.assertEqual(m["body"], "body")
        self.assertTrue(mb1.has_listeners())

        mb1.add_message(SidedMessage(side="side2", phase="phase2",
                                     body="body2", server_rx=0,
                                     msg_id="msgid"))
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "message")
        self.assertEqual(m["body"], "body2")

        c1.send("open", mailbox="mb1")
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "only one open per connection")

        # exercise the _stop() handler too, which is a nop
        mb1.close("side2", "happy", 1)
        mb1.close("side", "happy", 2)

    @inlineCallbacks
    def test_open_crowded(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        mbid = app.claim_nameplate("np1", "side1", 0)
        app.claim_nameplate("np1", "side2", 0)

        # the third open will signal crowding
        c1.send("open", mailbox=mbid)
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "crowded")

    @inlineCallbacks
    def test_add(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")
        mb1 = app.open_mailbox("mb1", "side2", 0)
        l1 = []; stop1 = []; stop1_f = lambda: stop1.append(True)
        mb1.add_listener("handle1", l1.append, stop1_f)

        c1.send("add") # didn't open first
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "must open mailbox before adding")

        c1.send("open", mailbox="mb1")

        c1.send("add", body="body") # missing phase=
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "missing 'phase'")

        c1.send("add", phase="phase") # missing body=
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "missing 'body'")

        c1.send("add", phase="phase", body="body")
        m = yield c1.next_non_ack() # echoed back
        self.assertEqual(m["type"], "message")
        self.assertEqual(m["body"], "body")

        self.assertEqual(len(l1), 1)
        self.assertEqual(l1[0].body, "body")

    @inlineCallbacks
    def test_close(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        c1.send("close", mood="mood") # must open first
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "close without mailbox must follow open")

        c1.send("open", mailbox="mb1")
        yield c1.sync()
        mb1 = app._mailboxes["mb1"]
        self.assertTrue(mb1.has_listeners())

        c1.send("close", mood="mood")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "closed")
        self.assertFalse(mb1.has_listeners())

        c1.send("close", mood="mood") # already closed
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error", m)
        self.assertEqual(err["error"], "only one close per connection")

    @inlineCallbacks
    def test_close_named(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")

        c1.send("open", mailbox="mb1")
        yield c1.sync()

        c1.send("close", mailbox="mb1", mood="mood")
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "closed")

    @inlineCallbacks
    def test_close_named_ignored(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")

        c1.send("close", mailbox="mb1", mood="mood") # no open first, ignored
        m = yield c1.next_non_ack()
        self.assertEqual(m["type"], "closed")

    @inlineCallbacks
    def test_close_named_mismatch(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")

        c1.send("open", mailbox="mb1")
        yield c1.sync()

        c1.send("close", mailbox="mb2", mood="mood")
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "open and close must use same mailbox")

    @inlineCallbacks
    def test_close_crowded(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        mbid = app.claim_nameplate("np1", "side1", 0)
        app.claim_nameplate("np1", "side2", 0)

        # a close that allocates a third side will signal crowding
        c1.send("close", mailbox=mbid)
        err = yield c1.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "crowded")


    @inlineCallbacks
    def test_disconnect(self):
        c1 = yield self.make_client()
        yield c1.next_non_ack()
        c1.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        c1.send("open", mailbox="mb1")
        yield c1.sync()
        mb1 = app._mailboxes["mb1"]
        self.assertTrue(mb1.has_listeners())

        yield c1.close()
        # wait for the server to notice the socket has closed
        started = time.time()
        while mb1.has_listeners() and (time.time()-started < 5.0):
            d = defer.Deferred()
            reactor.callLater(0.01, d.callback, None)
            yield d
        self.assertFalse(mb1.has_listeners())

    @inlineCallbacks
    def test_interrupted_client_nameplate(self):
        # a client's interactions with the server might be split over
        # multiple sequential WebSocket connections, e.g. when the server is
        # bounced and the client reconnects, or vice versa
        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        c.send("claim", nameplate="np1")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "claimed")
        mailbox_id = m["mailbox"]
        self.assertEqual(type(mailbox_id), type(""))
        np_row, side_rows = self._nameplate(app, "np1")
        claims = [(row["side"], row["claimed"]) for row in side_rows]
        self.assertEqual(claims, [("side", True)])
        c.close()
        yield c.d

        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        c.send("claim", nameplate="np1") # idempotent
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "claimed")
        self.assertEqual(m["mailbox"], mailbox_id) # mailbox id is stable
        np_row, side_rows = self._nameplate(app, "np1")
        claims = [(row["side"], row["claimed"]) for row in side_rows]
        self.assertEqual(claims, [("side", True)])
        c.close()
        yield c.d

        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        # we haven't done a claim with this particular connection, but we can
        # still send a release as long as we include the nameplate
        c.send("release", nameplate="np1") # release-without-claim
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "released")
        np_row, side_rows = self._nameplate(app, "np1")
        self.assertEqual(np_row, None)
        c.close()
        yield c.d

        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        # and the release is idempotent, when done on separate connections
        c.send("release", nameplate="np1")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "released")
        np_row, side_rows = self._nameplate(app, "np1")
        self.assertEqual(np_row, None)
        c.close()
        yield c.d


    @inlineCallbacks
    def test_interrupted_client_nameplate_reclaimed(self):
        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")

        # a new claim on a previously-closed nameplate is forbidden. We make
        # a new nameplate here and manually open a second claim on it, so the
        # nameplate stays alive long enough for the code check to happen.
        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        c.send("claim", nameplate="np2")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "claimed")
        app.claim_nameplate("np2", "side2", 0)
        c.send("release", nameplate="np2")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "released")
        np_row, side_rows = self._nameplate(app, "np2")
        claims = sorted([(row["side"], row["claimed"]) for row in side_rows])
        self.assertEqual(claims, [("side", 0), ("side2", 1)])
        c.close()
        yield c.d

        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        c.send("claim", nameplate="np2") # new claim is forbidden
        err = yield c.next_non_ack()
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"], "reclaimed")

        np_row, side_rows = self._nameplate(app, "np2")
        claims = sorted([(row["side"], row["claimed"]) for row in side_rows])
        self.assertEqual(claims, [("side", 0), ("side2", 1)])
        c.close()
        yield c.d

    @inlineCallbacks
    def test_interrupted_client_mailbox(self):
        # a client's interactions with the server might be split over
        # multiple sequential WebSocket connections, e.g. when the server is
        # bounced and the client reconnects, or vice versa
        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        app = self._server.get_app("appid")
        mb1 = app.open_mailbox("mb1", "side2", 0)
        mb1.add_message(SidedMessage(side="side2", phase="phase",
                                     body="body", server_rx=0,
                                     msg_id="msgid"))

        c.send("open", mailbox="mb1")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "message")
        self.assertEqual(m["body"], "body")
        self.assertTrue(mb1.has_listeners())
        c.close()
        yield c.d

        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        # open should be idempotent
        c.send("open", mailbox="mb1")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "message")
        self.assertEqual(m["body"], "body")
        mb_row, side_rows = self._mailbox(app, "mb1")
        openeds = [(row["side"], row["opened"]) for row in side_rows]
        self.assertIn(("side", 1), openeds) # TODO: why 1, and not True?

        # close on the same connection as open is ok
        c.send("close", mailbox="mb1", mood="mood")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "closed", m)
        mb_row, side_rows = self._mailbox(app, "mb1")
        openeds = [(row["side"], row["opened"]) for row in side_rows]
        self.assertIn(("side", 0), openeds)
        c.close()
        yield c.d

        # close (on a separate connection) is idempotent
        c = yield self.make_client()
        yield c.next_non_ack()
        c.send("bind", appid="appid", side="side")
        c.send("close", mailbox="mb1", mood="mood")
        m = yield c.next_non_ack()
        self.assertEqual(m["type"], "closed", m)
        mb_row, side_rows = self._mailbox(app, "mb1")
        openeds = [(row["side"], row["opened"]) for row in side_rows]
        self.assertIn(("side", 0), openeds)
        c.close()
        yield c.d


