import io
import mock
import treq
from twisted.trial import unittest
from twisted.internet.defer import inlineCallbacks
from ..web import make_web_server
from .common import ServerBase

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
        pass

    @inlineCallbacks
    def test_log(self):
        yield self._setup_relay(do_listen=True, web_log_requests=True)
        fakelog = io.BytesIO()
        self._site.logFile = fakelog
        yield treq.get("http://127.0.0.1:%d/" % self.rdv_ws_port,
                       persistent=False)
        lines = fakelog.getvalue().splitlines()
        self.assertEqual(len(lines), 1, lines)

    @inlineCallbacks
    def test_no_log(self):
        yield self._setup_relay(do_listen=True, web_log_requests=False)
        fakelog = io.BytesIO()
        self._site.logFile = fakelog
        yield treq.get("http://127.0.0.1:%d/" % self.rdv_ws_port,
                       persistent=False)
        lines = fakelog.getvalue().splitlines()
        self.assertEqual(len(lines), 0, lines)
