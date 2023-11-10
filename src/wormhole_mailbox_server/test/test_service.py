from __future__ import unicode_literals, print_function
from twisted.trial import unittest
from unittest import mock
from twisted.application.service import MultiService
from .. import server_tap

class Service(unittest.TestCase):
    def test_defaults(self):
        o = server_tap.Options()
        o.parseOptions([])
        cdb = object()
        udb = object()
        r = mock.Mock()
        ws = object()
        with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_channel_db", return_value=cdb) as ccdb:
            with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_usage_db", return_value=udb) as ccub:
                with mock.patch("wormhole_mailbox_server.server_tap.make_server", return_value=r) as ms:
                    with mock.patch("wormhole_mailbox_server.server_tap.make_web_server", return_value=ws) as mws:
                        s = server_tap.makeService(o)
        self.assertEqual(ccdb.mock_calls, [mock.call("relay.sqlite")])
        self.assertEqual(ccub.mock_calls, [mock.call(None)])
        self.assertEqual(ms.mock_calls, [mock.call(cdb, allow_list=True,
                                                   advertise_version=None,
                                                   signal_error=None,
                                                   welcome_motd=None,
                                                   blur_usage=None,
                                                   usage_db=udb,
                                                   log_file=None)])
        self.assertEqual(mws.mock_calls, [mock.call(r, True, [])])
        self.assertIsInstance(s, MultiService)
        self.assertEqual(len(r.mock_calls), 1) # setServiceParent

    def test_log_fd(self):
        o = server_tap.Options()
        o.parseOptions(["--log-fd=99"])
        fd = object()
        cdb = object()
        udb = object()
        r = mock.Mock()
        ws = object()
        with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_channel_db", return_value=cdb):
            with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_usage_db", return_value=udb):
                with mock.patch("wormhole_mailbox_server.server_tap.make_server", return_value=r) as ms:
                    with mock.patch("wormhole_mailbox_server.server_tap.make_web_server", return_value=ws):
                        with mock.patch("wormhole_mailbox_server.server_tap.os.fdopen",
                                        return_value=fd) as f:
                            server_tap.makeService(o)
        self.assertEqual(f.mock_calls, [mock.call(99, "w")])
        self.assertEqual(ms.mock_calls, [mock.call(cdb, allow_list=True,
                                                   advertise_version=None,
                                                   signal_error=None,
                                                   welcome_motd=None,
                                                   blur_usage=None,
                                                   usage_db=udb,
                                                   log_file=fd)])
