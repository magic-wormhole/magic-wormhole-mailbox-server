from __future__ import print_function, unicode_literals
from unittest import mock
from twisted.trial import unittest
from ..increase_rlimits import increase_rlimits

class RLimits(unittest.TestCase):
    def test_rlimit(self):
        def patch_r(name, *args, **kwargs):
            return mock.patch("wormhole_mailbox_server.increase_rlimits." + name, *args, **kwargs)
        fakelog = []
        def checklog(*expected):
            self.assertEqual(fakelog, list(expected))
            fakelog[:] = []
        NF = "NOFILE"
        mock_NF = patch_r("RLIMIT_NOFILE", NF)

        with patch_r("log.msg", fakelog.append):
            with patch_r("getrlimit", None):
                increase_rlimits()
            checklog("unable to import 'resource', leaving rlimit alone")

            with mock_NF:
                with patch_r("getrlimit", return_value=(20000, 30000)) as gr:
                    increase_rlimits()
                    self.assertEqual(gr.mock_calls, [mock.call(NF)])
                    checklog("RLIMIT_NOFILE.soft was 20000, leaving it alone")

                with patch_r("getrlimit", return_value=(10, 30000)) as gr:
                    with patch_r("setrlimit", side_effect=TypeError("other")):
                        with patch_r("log.err") as err:
                            increase_rlimits()
                        self.assertEqual(err.mock_calls, [mock.call()])
                        checklog("changing RLIMIT_NOFILE from (10,30000) to (30000,30000)",
                                 "other error during setrlimit, leaving it alone")

                    for maxlimit in [40000, 20000, 9000, 2000, 1000]:
                        def setrlimit(which, newlimit):
                            if newlimit[0] > maxlimit:
                                raise ValueError("nope")
                            return None
                        calls = []
                        expected = []
                        for tries in [30000, 10000, 3200, 1024]:
                            calls.append(mock.call(NF, (tries, 30000)))
                            expected.append("changing RLIMIT_NOFILE from (10,30000) to (%d,30000)" % tries)
                            if tries > maxlimit:
                                expected.append("error during setrlimit: nope")
                            else:
                                expected.append("setrlimit successful")
                                break
                        else:
                            expected.append("unable to change rlimit, leaving it alone")

                        with patch_r("setrlimit", side_effect=setrlimit) as sr:
                            increase_rlimits()
                        self.assertEqual(sr.mock_calls, calls)
                        checklog(*expected)
