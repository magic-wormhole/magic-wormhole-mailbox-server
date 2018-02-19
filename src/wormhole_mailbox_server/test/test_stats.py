from __future__ import print_function, unicode_literals
#import io, json
from twisted.trial import unittest
from ..database import create_channel_db, create_usage_db
from ..server import make_server, CrowdedError

class DB(unittest.TestCase):
    def make(self, with_usage_db=True):
        self._cdb = create_channel_db(":memory:")
        db = create_usage_db(":memory:") if with_usage_db else None
        s = make_server(self._cdb, usage_db=db, blur_usage=None)
        app = s.get_app("appid")
        return s, db, app

    def test_current(self):
        s, db, app = self.make()
        s.dump_stats(456, rebooted=451)
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchall(),
                         [dict(rebooted=451, updated=456,
                               connections_websocket=0),
                          ])

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
