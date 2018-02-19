import io
import mock
import treq
from twisted.trial import unittest
from twisted.internet import defer, reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from ..web import make_web_server
from .common import ServerBase
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
