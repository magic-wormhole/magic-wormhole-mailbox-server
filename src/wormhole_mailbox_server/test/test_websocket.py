import json
from twisted.trial import unittest
from twisted.internet.defer import inlineCallbacks
from twisted.internet.address import IPv4Address
from ..server_websocket import WebSocketServerFactory
from ..connections import ConnectionTable
from autobahn.twisted.testing import create_pumper, create_memory_agent, MemoryReactorClock
from autobahn.twisted.websocket import WebSocketClientProtocol


class FakeServer:
    """
    Fake enough of the internal 'Server' object to appease the
    WebSocket server.

    """
    def __init__(self):
        self._connection_table = ConnectionTable(None)

    def get_welcome(self):
        return {
            "motd": "fake message of the day"
        }

    def get_log_requests(self):
        return False

    def get_address_id(self, peer_type, peer_host):
        return None

    def connection_established(self, address_id, now):
        c = self._connection_table.established(address_id, now)
        return c


class WebSocket(unittest.TestCase):
    """
    Details of the server WebSocket protocol
    """

    def setUp(self):
        self.pumper = create_pumper()
        self.reactor = MemoryReactorClock()
        return self.pumper.start()

    def tearDown(self):
        return self.pumper.stop()

    def create_server_protocol(self):
        """
        Used by the Agent to create the in-memory transport server-side
        WebSocket protocol (we actually create the 'real' protocol
        objects since that is what we're testing here.)
        """
        factory = WebSocketServerFactory(
            "ws://localhost:4000/v1",
            FakeServer(),
        )
        addr = IPv4Address("TCP", "localhost", 4000)
        return factory.buildProtocol(addr)

    @inlineCallbacks
    def test_server_version_string(self):
        """
        Our server version string from Autobahn should make sense
        """
        server_header = None
        agent = create_memory_agent(
            self.reactor,
            self.pumper,
            self.create_server_protocol
        )

        class FakeClient(WebSocketClientProtocol):
            def onConnect(self, cr):
                nonlocal server_header
                server_header = cr.headers.get("server")

        proto = yield agent.open("ws://localhost:4000/v1", dict(), FakeClient)
        proto.sendClose()
        yield proto.is_closed

        assert "Magic Wormhole" in server_header, "Incorrect Server: header sent"

    @inlineCallbacks
    def test_reflected_address(self):
        """
        The Welcome message should include our address information
        """
        welcome = None
        agent = create_memory_agent(
            self.reactor,
            self.pumper,
            self.create_server_protocol
        )

        class FakeClient(WebSocketClientProtocol):
            def onMessage(self, payload, isBinary):
                js = json.loads(payload)
                nonlocal welcome
                if welcome is None:
                    welcome = js.get("welcome", None)
                return super().onMessage(payload, isBinary)

        proto = yield agent.open("ws://localhost:4000/v1", dict(), FakeClient)
        proto.sendClose()
        yield proto.is_closed

        assert welcome is not None, "Failed to receive Welcome message"
        ya = welcome.get("your-address", None)
        assert ya, "Expected 'your-address' in Welcome message"
        assert ya["port"] == 31337
        assert "ipv4" in ya or "ipv6" in ya, "Expected either IPv4 or IPv6 address"

    @inlineCallbacks
    def test_reflected_caddy(self):
        """
        The Welcome message should include our address information
        when sent via x-real-ip headers
        """
        welcome = None

        headers = {
            "x-real-ip": "127.1.2.3",
            "x-real-port": "54321",
        }

        agent = create_memory_agent(
            self.reactor,
            self.pumper,
            self.create_server_protocol,
        )

        class FakeClient(WebSocketClientProtocol):
            def onMessage(self, payload, isBinary):
                js = json.loads(payload)
                nonlocal welcome
                if welcome is None:
                    welcome = js.get("welcome", None)
                return super().onMessage(payload, isBinary)

        proto = yield agent.open("ws://localhost:4000/v1", {"headers": headers}, FakeClient)
        proto.sendClose()
        yield proto.is_closed

        assert welcome is not None, "Failed to receive Welcome message"
        self.assertEqual(
            welcome["your-address"],
            {
                "ipv4": "127.1.2.3",
                "port": 54321,
            }
        )

    @inlineCallbacks
    def test_reflected_caddyv6(self):
        """
        The Welcome message should include our address information
        when sent via x-real-ip headers (IPv6 version)
        """
        welcome = None

        headers = {
            "x-real-ip": "::1",
            "x-real-port": "54321",
        }

        agent = create_memory_agent(
            self.reactor,
            self.pumper,
            self.create_server_protocol,
        )

        class FakeClient(WebSocketClientProtocol):
            def onMessage(self, payload, isBinary):
                js = json.loads(payload)
                nonlocal welcome
                if welcome is None:
                    welcome = js.get("welcome", None)
                return super().onMessage(payload, isBinary)

        proto = yield agent.open("ws://localhost:4000/v1", {"headers": headers}, FakeClient)
        proto.sendClose()
        yield proto.is_closed

        assert welcome is not None, "Failed to receive Welcome message"
        self.assertEqual(
            welcome["your-address"],
            {
                "ipv6": "::1",
                "port": 54321,
            }
        )
