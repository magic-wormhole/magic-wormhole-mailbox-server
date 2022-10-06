from __future__ import unicode_literals, print_function
from twisted.python.usage import UsageError
from twisted.trial import unittest
from .. import server_tap

PORT = "tcp:4000:interface=\:\:"

class Config(unittest.TestCase):
    def test_defaults(self):
        o = server_tap.Options()
        o.parseOptions([])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_advertise_version(self):
        o = server_tap.Options()
        o.parseOptions(["--advertise-version=1.0"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": "1.0",
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_blur(self):
        o = server_tap.Options()
        o.parseOptions(["--blur-usage=60"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": 60,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_channel_db(self):
        o = server_tap.Options()
        o.parseOptions(["--channel-db=other.sqlite"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "other.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_disallow_list(self):
        o = server_tap.Options()
        o.parseOptions(["--disallow-list"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": False,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_log_fd(self):
        o = server_tap.Options()
        o.parseOptions(["--log-fd=5"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": 5,
                             "websocket-protocol-options": [],
                             })

    def test_port(self):
        o = server_tap.Options()
        o.parseOptions(["-p", "tcp:5555"])
        self.assertEqual(o, {"port": "tcp:5555",
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

        o = server_tap.Options()
        o.parseOptions(["--port=tcp:5555"])
        self.assertEqual(o, {"port": "tcp:5555",
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_signal_error(self):
        o = server_tap.Options()
        o.parseOptions(["--signal-error=ohnoes"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": "ohnoes",
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_usage_db(self):
        o = server_tap.Options()
        o.parseOptions(["--usage-db=usage.sqlite"])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": "usage.sqlite",
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [],
                             })

    def test_websocket_protocol_option_1(self):
        o = server_tap.Options()
        o.parseOptions(["--websocket-protocol-option", 'foo="bar"'])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [("foo", "bar")],
                             })

    def test_websocket_protocol_option_2(self):
        o = server_tap.Options()
        o.parseOptions(["--websocket-protocol-option", 'foo="bar"',
                        "--websocket-protocol-option", 'baz=[1,"buz"]',
                        ])
        self.assertEqual(o, {"port": PORT,
                             "channel-db": "relay.sqlite",
                             "disallow-list": 0,
                             "allow-list": True,
                             "advertise-version": None,
                             "signal-error": None,
                             "usage-db": None,
                             "blur-usage": None,
                             "motd": None,
                             "log-fd": None,
                             "websocket-protocol-options": [("foo", "bar"),
                                                            ("baz", [1, "buz"]),
                                                            ],
                             })

    def test_websocket_protocol_option_errors(self):
        o = server_tap.Options()
        with self.assertRaises(UsageError):
            o.parseOptions(["--websocket-protocol-option", 'foo'])
        with self.assertRaises(UsageError):
            # I would be nice if this worked, but the 'bar' isn't JSON. To
            # enable passing lists and more complicated things as values,
            # simple string values must be passed with additional quotes
            # (e.g. '"bar"')
            o.parseOptions(["--websocket-protocol-option", 'foo=bar'])

    def test_string(self):
        o = server_tap.Options()
        s = str(o)
        self.assertIn("This plugin sets up a 'Mailbox' server", s)
        self.assertIn("--blur-usage=", s)
        self.assertIn("round logged access times to improve privacy", s)

