from __future__ import print_function, unicode_literals
#import io, json
from twisted.trial import unittest
from ..database import create_channel_db, create_usage_db
from ..server import make_server, CrowdedError

class _Make:
    def make(self, blur_usage=None, with_usage_db=True):
        self._cdb = create_channel_db(":memory:")
        db = create_usage_db(":memory:") if with_usage_db else None
        s = make_server(self._cdb, usage_db=db, blur_usage=blur_usage)
        app = s.get_app("appid")
        return s, db, app

class Current(_Make, unittest.TestCase):
    def test_current_no_mailboxes(self):
        s, db, app = self.make()
        s.dump_stats(456, rebooted=451)
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchall(),
                         [dict(rebooted=451, updated=456, blur_time=None,
                               connections_websocket=0),
                          ])

    def test_current_no_listeners(self):
        s, db, app = self.make()
        app.open_mailbox("m1", "s1", 1)
        s.dump_stats(456, rebooted=451)
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchall(),
                         [dict(rebooted=451, updated=456, blur_time=None,
                               connections_websocket=0),
                          ])

    def test_current_one_listener(self):
        s, db, app = self.make()
        mbox = app.open_mailbox("m1", "s1", 1)
        mbox.add_listener("h1", lambda sm: None, lambda: None)
        s.dump_stats(456, rebooted=451)
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchall(),
                         [dict(rebooted=451, updated=456, blur_time=None,
                               connections_websocket=1),
                          ])

class ClientVersion(_Make, unittest.TestCase):
    def test_add_version(self):
        s, db, app = self.make()
        app.log_client_version(451, "side1", ("python", "1.2.3"))
        self.assertEqual(db.execute("SELECT * FROM `client_versions`").fetchall(),
                         [dict(app_id="appid", connect_time=451, side="side1",
                               implementation="python", version="1.2.3")])

    def test_add_version_extra_fields(self):
        s, db, app = self.make()
        app.log_client_version(451, "side1", ("python", "1.2.3", "extra"))
        self.assertEqual(db.execute("SELECT * FROM `client_versions`").fetchall(),
                         [dict(app_id="appid", connect_time=451, side="side1",
                               implementation="python", version="1.2.3")])

    def test_blur(self):
        s, db, app = self.make(blur_usage=100)
        app.log_client_version(451, "side1", ("python", "1.2.3"))
        self.assertEqual(db.execute("SELECT * FROM `client_versions`").fetchall(),
                         [dict(app_id="appid", connect_time=400, side="side1",
                               implementation="python", version="1.2.3")])

    def test_no_usage_db(self):
        s, db, app = self.make(with_usage_db=False)
        app.log_client_version(451, "side1", ("python", "1.2.3"))

class Nameplate(_Make, unittest.TestCase):
    def test_nameplate_happy(self):
        s, db, app = self.make()
        app.claim_nameplate("n1", "s1", 1)
        app.claim_nameplate("n1", "s2", 3)
        app.release_nameplate("n1", "s1", 6)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [])
        app.release_nameplate("n1", "s2", 10)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [dict(app_id="appid", result="happy",
                               started=1, waiting_time=2, total_time=9)])

    def test_nameplate_lonely(self):
        s, db, app = self.make()
        app.claim_nameplate("n1", "s1", 1)
        app.release_nameplate("n1", "s1", 6)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [dict(app_id="appid", result="lonely",
                               started=1, waiting_time=None, total_time=5)])

    def test_nameplate_pruney(self):
        s, db, app = self.make()
        app.claim_nameplate("n1", "s1", 1)
        app.prune(10, 5) # prune at t=10, anything earlier than 5 is "old"
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [dict(app_id="appid", result="pruney",
                               started=1, waiting_time=None, total_time=9)])

    def test_nameplate_crowded(self):
        s, db, app = self.make()
        app.claim_nameplate("n1", "s1", 1)
        app.claim_nameplate("n1", "s2", 2)
        with self.assertRaises(CrowdedError):
            app.claim_nameplate("n1", "s3", 3)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [])
        app.release_nameplate("n1", "s1", 4)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [])
        app.release_nameplate("n1", "s2", 5)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [])
        #print(self._cdb.execute("SELECT * FROM `nameplates`").fetchall())
        #print(self._cdb.execute("SELECT * FROM `nameplate_sides`").fetchall())
        # TODO: to get "crowded", we need all three sides to release the
        # nameplate, even though the third side threw CrowdedError and thus
        # probably doesn't think it has a claim
        app.release_nameplate("n1", "s3", 6)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [dict(app_id="appid", result="crowded",
                               started=1, waiting_time=1, total_time=5)])

    def test_nameplate_crowded_pruned(self):
        s, db, app = self.make()
        app.claim_nameplate("n1", "s1", 1)
        app.claim_nameplate("n1", "s2", 2)
        with self.assertRaises(CrowdedError):
            app.claim_nameplate("n1", "s3", 3)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [])
        app.prune(10, 5)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [dict(app_id="appid", result="crowded",
                               started=1, waiting_time=1, total_time=9)])

    def test_no_db(self):
        s, db, app = self.make(with_usage_db=False)
        app.claim_nameplate("n1", "s1", 1)
        app.release_nameplate("n1", "s1", 6)
        s.dump_stats(3, 1)

    def test_nameplate_happy_blur_usage(self):
        s, db, app = self.make(blur_usage=20)
        app.claim_nameplate("n1", "s1", 21)
        app.claim_nameplate("n1", "s2", 23)
        app.release_nameplate("n1", "s1", 26)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [])
        app.release_nameplate("n1", "s2", 30)
        self.assertEqual(db.execute("SELECT * FROM `nameplates`").fetchall(),
                         [dict(app_id="appid", result="happy",
                               started=20, waiting_time=2, total_time=9)])

class Mailbox(_Make, unittest.TestCase):
    def test_mailbox_prune_quiet(self):
        s, db, app = self.make()
        app.claim_nameplate("n1", "s1", 1)
        app.release_nameplate("n1", "s1", 2)
        app.prune(10, 5)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="pruney",
                               started=1, waiting_time=None, total_time=9)])

    def test_mailbox_lonely(self):
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox.close("s1", "mood-ignored", 4)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="lonely",
                               started=1, waiting_time=None, total_time=3)])

    def test_mailbox_happy(self):
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox1 = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox2 = app.open_mailbox(mid, "s2", 4)
        mbox1.close("s1", "happy", 5)
        mbox2.close("s2", "happy", 6)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="happy",
                               started=1, waiting_time=3, total_time=5)])

    def test_mailbox_happy_blur_usage(self):
        s, db, app = self.make(blur_usage=20)
        mid = app.claim_nameplate("n1", "s1", 21)
        mbox1 = app.open_mailbox(mid, "s1", 22)
        app.release_nameplate("n1", "s1", 23)
        mbox2 = app.open_mailbox(mid, "s2", 24)
        mbox1.close("s1", "happy", 25)
        mbox2.close("s2", "happy", 26)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="happy",
                               started=20, waiting_time=3, total_time=5)])

    def test_mailbox_lonely_connected(self):
        # I don't think this could actually happen. It requires both sides to
        # connect, but then at least one side says they're lonely when they
        # close.
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox1 = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox2 = app.open_mailbox(mid, "s2", 4)
        mbox1.close("s1", "lonely", 5)
        mbox2.close("s2", "happy", 6)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="lonely",
                               started=1, waiting_time=3, total_time=5)])

    def test_mailbox_scary(self):
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox1 = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox2 = app.open_mailbox(mid, "s2", 4)
        mbox1.close("s1", "scary", 5)
        mbox2.close("s2", "happy", 6)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="scary",
                               started=1, waiting_time=3, total_time=5)])

    def test_mailbox_errory(self):
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox1 = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox2 = app.open_mailbox(mid, "s2", 4)
        mbox1.close("s1", "errory", 5)
        mbox2.close("s2", "happy", 6)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="errory",
                               started=1, waiting_time=3, total_time=5)])

    def test_mailbox_errory_scary(self):
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox1 = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox2 = app.open_mailbox(mid, "s2", 4)
        mbox1.close("s1", "errory", 5)
        mbox2.close("s2", "scary", 6)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="scary",
                               started=1, waiting_time=3, total_time=5)])

    def test_mailbox_crowded(self):
        s, db, app = self.make()
        mid = app.claim_nameplate("n1", "s1", 1)
        mbox1 = app.open_mailbox(mid, "s1", 2)
        app.release_nameplate("n1", "s1", 3)
        mbox2 = app.open_mailbox(mid, "s2", 4)
        with self.assertRaises(CrowdedError):
            app.open_mailbox(mid, "s3", 5)
        mbox1.close("s1", "happy", 6)
        mbox2.close("s2", "happy", 7)
        # again, not realistic
        mbox2.close("s3", "happy", 8)
        self.assertEqual(db.execute("SELECT * FROM `mailboxes`").fetchall(),
                         [dict(app_id="appid", for_nameplate=1, result="crowded",
                               started=1, waiting_time=3, total_time=7)])

## class LogToStdout(unittest.TestCase):
##     def test_log(self):
##         # emit lines of JSON to log_file, if set
##         log_file = io.StringIO()
##         t = Transit(blur_usage=None, log_file=log_file, usage_db=None)
##         t.recordUsage(started=123, result="happy", total_bytes=100,
##                       total_time=10, waiting_time=2)
##         self.assertEqual(json.loads(log_file.getvalue()),
##                          {"started": 123, "total_time": 10,
##                           "waiting_time": 2, "total_bytes": 100,
##                           "mood": "happy"})

##     def test_log_blurred(self):
##         # if blurring is enabled, timestamps should be rounded to the
##         # requested amount, and sizes should be rounded up too
##         log_file = io.StringIO()
##         t = Transit(blur_usage=60, log_file=log_file, usage_db=None)
##         t.recordUsage(started=123, result="happy", total_bytes=11999,
##                       total_time=10, waiting_time=2)
##         self.assertEqual(json.loads(log_file.getvalue()),
##                          {"started": 120, "total_time": 10,
##                           "waiting_time": 2, "total_bytes": 20000,
##                           "mood": "happy"})

##     def test_do_not_log(self):
##         t = Transit(blur_usage=60, log_file=None, usage_db=None)
##         t.recordUsage(started=123, result="happy", total_bytes=11999,
##                       total_time=10, waiting_time=2)
