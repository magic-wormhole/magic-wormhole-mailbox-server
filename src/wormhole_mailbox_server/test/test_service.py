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
        aidb = object()
        r = mock.Mock()
        ws = object()
        with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_channel_db", return_value=cdb) as c_cdb:
            with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_usage_db", return_value=udb) as c_udb:
                with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_addrid_db", return_value=aidb) as c_aidb:
                    with mock.patch("wormhole_mailbox_server.server_tap.make_server", return_value=r) as ms:
                        with mock.patch("wormhole_mailbox_server.server_tap.make_web_server", return_value=ws) as mws:
                            s = server_tap.makeService(o)
        self.assertEqual(c_cdb.mock_calls, [mock.call("relay.sqlite")])
        self.assertEqual(c_udb.mock_calls, [])
        self.assertEqual(c_aidb.mock_calls, [])
        self.assertEqual(ms.mock_calls, [mock.call(cdb, allow_list=True,
                                                   advertise_version=None,
                                                   signal_error=None,
                                                   welcome_motd=None,
                                                   blur_usage=None,
                                                   usage_db=None,
                                                   addrid_db=None,
                                                   )])
        self.assertEqual(mws.mock_calls, [mock.call(r, True, [])])
        self.assertIsInstance(s, MultiService)
        self.assertEqual(len(r.mock_calls), 3) # setServiceParent, check_addrid_generation, clear_connections

    def test_usagedb(self):
        o = server_tap.Options()
        o.parseOptions(["--usage-db=usage.sqlite"])
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
        self.assertEqual(ccub.mock_calls, [mock.call("usage.sqlite")])
        self.assertEqual(ms.mock_calls, [mock.call(cdb, allow_list=True,
                                                   advertise_version=None,
                                                   signal_error=None,
                                                   welcome_motd=None,
                                                   blur_usage=None,
                                                   usage_db=udb,
                                                   addrid_db=None,
                                                   )])
        self.assertEqual(mws.mock_calls, [mock.call(r, True, [])])
        self.assertIsInstance(s, MultiService)
        self.assertEqual(len(r.mock_calls), 3) # setServiceParent, check_addrid_generation, clear_connections

    def test_addriddb(self):
        o = server_tap.Options()
        o.parseOptions(["--addrid-db=addresses.sqlite"])
        cdb = object()
        udb = object()
        aidb = object()
        r = mock.Mock()
        ws = object()
        with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_channel_db", return_value=cdb) as ccdb:
            with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_usage_db", return_value=udb) as ccub:
                with mock.patch("wormhole_mailbox_server.server_tap.create_or_upgrade_addrid_db", return_value=aidb) as c_aidb:
                    with mock.patch("wormhole_mailbox_server.server_tap.make_server", return_value=r) as ms:
                        with mock.patch("wormhole_mailbox_server.server_tap.make_web_server", return_value=ws) as mws:
                            s = server_tap.makeService(o)
        self.assertEqual(ccdb.mock_calls, [mock.call("relay.sqlite")])
        self.assertEqual(ccub.mock_calls, [])
        self.assertEqual(c_aidb.mock_calls, [mock.call("addresses.sqlite")])
        self.assertEqual(ms.mock_calls, [mock.call(cdb, allow_list=True,
                                                   advertise_version=None,
                                                   signal_error=None,
                                                   welcome_motd=None,
                                                   blur_usage=None,
                                                   usage_db=None,
                                                   addrid_db=aidb,
                                                   )])
        self.assertEqual(mws.mock_calls, [mock.call(r, True, [])])
        self.assertIsInstance(s, MultiService)
        self.assertEqual(len(r.mock_calls), 3) # setServiceParent, check_addrid_generation, clear_connections
