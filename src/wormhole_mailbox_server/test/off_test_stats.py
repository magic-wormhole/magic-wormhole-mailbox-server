from __future__ import print_function, unicode_literals
import os, io, json, sqlite3
import mock
from twisted.trial import unittest
from ..transit_server import Transit
from .. import database

class DB(unittest.TestCase):
    def open_db(self, dbfile):
        db = sqlite3.connect(dbfile)
        database._initialize_db_connection(db)
        return db

    def test_db(self):
        d = self.mktemp()
        os.mkdir(d)
        usage_db = os.path.join(d, "usage.sqlite")
        with mock.patch("time.time", return_value=456):
            t = Transit(blur_usage=None, log_file=None, usage_db=usage_db)
        db = self.open_db(usage_db)

        with mock.patch("time.time", return_value=457):
            t.recordUsage(started=123, result="happy", total_bytes=100,
                          total_time=10, waiting_time=2)
        self.assertEqual(db.execute("SELECT * FROM `usage`").fetchall(),
                         [dict(result="happy", started=123,
                               total_bytes=100, total_time=10, waiting_time=2),
                          ])
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchone(),
                         dict(rebooted=456, updated=457,
                              incomplete_bytes=0,
                              waiting=0, connected=0))

        with mock.patch("time.time", return_value=458):
            t.recordUsage(started=150, result="errory", total_bytes=200,
                          total_time=11, waiting_time=3)
        self.assertEqual(db.execute("SELECT * FROM `usage`").fetchall(),
                         [dict(result="happy", started=123,
                               total_bytes=100, total_time=10, waiting_time=2),
                          dict(result="errory", started=150,
                               total_bytes=200, total_time=11, waiting_time=3),
                          ])
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchone(),
                         dict(rebooted=456, updated=458,
                              incomplete_bytes=0,
                              waiting=0, connected=0))

        with mock.patch("time.time", return_value=459):
            t.timerUpdateStats()
        self.assertEqual(db.execute("SELECT * FROM `current`").fetchone(),
                         dict(rebooted=456, updated=459,
                              incomplete_bytes=0,
                              waiting=0, connected=0))

    def test_no_db(self):
        t = Transit(blur_usage=None, log_file=None, usage_db=None)

        t.recordUsage(started=123, result="happy", total_bytes=100,
                      total_time=10, waiting_time=2)
        t.timerUpdateStats()

class LogToStdout(unittest.TestCase):
    def test_log(self):
        # emit lines of JSON to log_file, if set
        log_file = io.StringIO()
        t = Transit(blur_usage=None, log_file=log_file, usage_db=None)
        t.recordUsage(started=123, result="happy", total_bytes=100,
                      total_time=10, waiting_time=2)
        self.assertEqual(json.loads(log_file.getvalue()),
                         {"started": 123, "total_time": 10,
                          "waiting_time": 2, "total_bytes": 100,
                          "mood": "happy"})

    def test_log_blurred(self):
        # if blurring is enabled, timestamps should be rounded to the
        # requested amount, and sizes should be rounded up too
        log_file = io.StringIO()
        t = Transit(blur_usage=60, log_file=log_file, usage_db=None)
        t.recordUsage(started=123, result="happy", total_bytes=11999,
                      total_time=10, waiting_time=2)
        self.assertEqual(json.loads(log_file.getvalue()),
                         {"started": 120, "total_time": 10,
                          "waiting_time": 2, "total_bytes": 20000,
                          "mood": "happy"})

    def test_do_not_log(self):
        t = Transit(blur_usage=60, log_file=None, usage_db=None)
        t.recordUsage(started=123, result="happy", total_bytes=11999,
                      total_time=10, waiting_time=2)
