from __future__ import print_function, unicode_literals
from unittest import mock
from twisted.trial import unittest
from twisted.python import log
from .common import ServerBase, _Util
from ..server import (make_server, Usage,
                      SidedMessage, CrowdedError, AppNamespace)
from ..database import create_channel_db, create_usage_db


class Server(_Util, ServerBase, unittest.TestCase):
    def test_apps(self):
        app1 = self._server.get_app("appid1")
        self.assertIdentical(app1, self._server.get_app("appid1"))
        app2 = self._server.get_app("appid2")
        self.assertNotIdentical(app1, app2)

    def test_nameplate_allocation(self):
        app = self._server.get_app("appid")
        nids = set()
        # this takes a second, and claims all the short-numbered nameplates
        def add():
            nameplate_id = app.allocate_nameplate("side1", 0)
            self.assertEqual(type(nameplate_id), type(""))
            nid = int(nameplate_id)
            nids.add(nid)
        for i in range(9): add()
        self.assertNotIn(0, nids)
        self.assertEqual(set(range(1,10)), nids)

        for i in range(100-10): add()
        self.assertEqual(len(nids), 99)
        self.assertEqual(set(range(1,100)), nids)

        for i in range(1000-100): add()
        self.assertEqual(len(nids), 999)
        self.assertEqual(set(range(1,1000)), nids)

        add()
        self.assertEqual(len(nids), 1000)
        biggest = max(nids)
        self.assert_(1000 <= biggest < 1000000, biggest)

    def test_nameplate_allocation_failure(self):
        app = self._server.get_app("appid")
        # pretend to fill all 1M <7-digit nameplates, it should give up
        # eventually
        def _get_nameplate_ids():
            return set(("%d" % id_int for id_int in range(1, 1000*1000)))
        app._get_nameplate_ids = _get_nameplate_ids
        with self.assertRaises(ValueError) as e:
            app.allocate_nameplate("side1", 0)
        self.assertIn("unable to find a free nameplate-id", str(e.exception))

    def test_nameplate(self):
        app = self._server.get_app("appid")
        name = app.allocate_nameplate("side1", 0)
        self.assertEqual(type(name), type(""))
        nid = int(name)
        self.assert_(0 < nid < 10, nid)
        self.assertEqual(app.get_nameplate_ids(), set([name]))
        # allocate also does a claim
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["side"], "side1")
        self.assertEqual(side_rows[0]["added"], 0)

        # duplicate claims by the same side are combined
        mailbox_id = app.claim_nameplate(name, "side1", 1)
        self.assertEqual(type(mailbox_id), type(""))
        self.assertEqual(mailbox_id, np_row["mailbox_id"])
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["added"], 0)
        self.assertEqual(mailbox_id, np_row["mailbox_id"])

        # and they don't updated the 'added' time
        mailbox_id2 = app.claim_nameplate(name, "side1", 2)
        self.assertEqual(mailbox_id, mailbox_id2)
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["added"], 0)

        # claim by the second side is new
        mailbox_id3 = app.claim_nameplate(name, "side2", 3)
        self.assertEqual(mailbox_id, mailbox_id3)
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 2)
        self.assertEqual(sorted([row["side"] for row in side_rows]),
                         sorted(["side1", "side2"]))
        self.assertIn(("side2", 3),
                      [(row["side"], row["added"]) for row in side_rows])

        # a third claim marks the nameplate as "crowded", and adds a third
        # claim (which must be released later), but leaves the two existing
        # claims alone
        self.assertRaises(CrowdedError,
                          app.claim_nameplate, name, "side3", 4)
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 3)

        # releasing a non-existent nameplate is ignored
        app.release_nameplate(name+"not", "side4", 0)

        # releasing a side that never claimed the nameplate is ignored
        app.release_nameplate(name, "side4", 0)
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(len(side_rows), 3)

        # releasing one side leaves the second claim
        app.release_nameplate(name, "side1", 5)
        np_row, side_rows = self._nameplate(app, name)
        claims = [(row["side"], row["claimed"]) for row in side_rows]
        self.assertIn(("side1", False), claims)
        self.assertIn(("side2", True), claims)
        self.assertIn(("side3", True), claims)

        # releasing one side multiple times is ignored
        app.release_nameplate(name, "side1", 5)
        np_row, side_rows = self._nameplate(app, name)
        claims = [(row["side"], row["claimed"]) for row in side_rows]
        self.assertIn(("side1", False), claims)
        self.assertIn(("side2", True), claims)
        self.assertIn(("side3", True), claims)

        # release the second side
        app.release_nameplate(name, "side2", 6)
        np_row, side_rows = self._nameplate(app, name)
        claims = [(row["side"], row["claimed"]) for row in side_rows]
        self.assertIn(("side1", False), claims)
        self.assertIn(("side2", False), claims)
        self.assertIn(("side3", True), claims)

        # releasing the third side frees the nameplate, and adds usage
        app.release_nameplate(name, "side3", 7)
        np_row, side_rows = self._nameplate(app, name)
        self.assertEqual(np_row, None)
        usage = app._usage_db.execute("SELECT * FROM `nameplates`").fetchone()
        self.assertEqual(usage["app_id"], "appid")
        self.assertEqual(usage["started"], 0)
        self.assertEqual(usage["waiting_time"], 3)
        self.assertEqual(usage["total_time"], 7)
        self.assertEqual(usage["result"], "crowded")


    def test_mailbox(self):
        app = self._server.get_app("appid")
        mailbox_id = "mid"
        m1 = app.open_mailbox(mailbox_id, "side1", 0)

        mb_row, side_rows = self._mailbox(app, mailbox_id)
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["side"], "side1")
        self.assertEqual(side_rows[0]["added"], 0)

        # opening the same mailbox twice, by the same side, gets the same
        # object, and does not update the "added" timestamp
        self.assertIdentical(m1, app.open_mailbox(mailbox_id, "side1", 1))
        mb_row, side_rows = self._mailbox(app, mailbox_id)
        self.assertEqual(len(side_rows), 1)
        self.assertEqual(side_rows[0]["side"], "side1")
        self.assertEqual(side_rows[0]["added"], 0)

        # opening a second side gets the same object, and adds a new claim
        self.assertIdentical(m1, app.open_mailbox(mailbox_id, "side2", 2))
        mb_row, side_rows = self._mailbox(app, mailbox_id)
        self.assertEqual(len(side_rows), 2)
        adds = [(row["side"], row["added"]) for row in side_rows]
        self.assertIn(("side1", 0), adds)
        self.assertIn(("side2", 2), adds)

        # a third open marks it as crowded
        self.assertRaises(CrowdedError,
                          app.open_mailbox, mailbox_id, "side3", 3)
        mb_row, side_rows = self._mailbox(app, mailbox_id)
        self.assertEqual(len(side_rows), 3)
        m1.close("side3", "company", 4)

        # closing a side that never claimed the mailbox is ignored
        m1.close("side4", "mood", 4)
        mb_row, side_rows = self._mailbox(app, mailbox_id)
        self.assertEqual(len(side_rows), 3)

        # closing one side leaves the second claim
        m1.close("side1", "mood", 5)
        mb_row, side_rows = self._mailbox(app, mailbox_id)
        sides = [(row["side"], row["opened"], row["mood"]) for row in side_rows]
        self.assertIn(("side1", False, "mood"), sides)
        self.assertIn(("side2", True, None), sides)
        self.assertIn(("side3", False, "company"), sides)

        # closing one side multiple times is ignored
        m1.close("side1", "mood", 6)
        mb_row, side_rows = self._mailbox(app, mailbox_id)
        sides = [(row["side"], row["opened"], row["mood"]) for row in side_rows]
        self.assertIn(("side1", False, "mood"), sides)
        self.assertIn(("side2", True, None), sides)
        self.assertIn(("side3", False, "company"), sides)

        l1 = []; stop1 = []; stop1_f = lambda: stop1.append(True)
        m1.add_listener("handle1", l1.append, stop1_f)

        # closing the second side frees the mailbox, and adds usage
        m1.close("side2", "mood", 7)
        self.assertEqual(stop1, [True])

        mb_row, side_rows = self._mailbox(app, mailbox_id)
        self.assertEqual(mb_row, None)
        usage = app._usage_db.execute("SELECT * FROM `mailboxes`").fetchone()
        self.assertEqual(usage["app_id"], "appid")
        self.assertEqual(usage["started"], 0)
        self.assertEqual(usage["waiting_time"], 2)
        self.assertEqual(usage["total_time"], 7)
        self.assertEqual(usage["result"], "crowded")

    def test_messages(self):
        app = self._server.get_app("appid")
        mailbox_id = "mid"
        m1 = app.open_mailbox(mailbox_id, "side1", 0)
        m1.add_message(SidedMessage(side="side1", phase="phase",
                                    body="body", server_rx=1,
                                    msg_id="msgid"))
        msgs = self._messages(app)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["body"], "body")

        l1 = []; stop1 = []; stop1_f = lambda: stop1.append(True)
        l2 = []; stop2 = []; stop2_f = lambda: stop2.append(True)
        old = m1.add_listener("handle1", l1.append, stop1_f)
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0].side, "side1")
        self.assertEqual(old[0].body, "body")

        m1.add_message(SidedMessage(side="side1", phase="phase2",
                                    body="body2", server_rx=1,
                                    msg_id="msgid"))
        self.assertEqual(len(l1), 1)
        self.assertEqual(l1[0].body, "body2")
        old = m1.add_listener("handle2", l2.append, stop2_f)
        self.assertEqual(len(old), 2)

        m1.add_message(SidedMessage(side="side1", phase="phase3",
                                    body="body3", server_rx=1,
                                    msg_id="msgid"))
        self.assertEqual(len(l1), 2)
        self.assertEqual(l1[-1].body, "body3")
        self.assertEqual(len(l2), 1)
        self.assertEqual(l2[-1].body, "body3")

        m1.remove_listener("handle1")

        m1.add_message(SidedMessage(side="side1", phase="phase4",
                                    body="body4", server_rx=1,
                                    msg_id="msgid"))
        self.assertEqual(len(l1), 2)
        self.assertEqual(l1[-1].body, "body3")
        self.assertEqual(len(l2), 2)
        self.assertEqual(l2[-1].body, "body4")

        m1._shutdown()
        self.assertEqual(stop1, [])
        self.assertEqual(stop2, [True])

        # message adds are not idempotent: clients filter duplicates
        m1.add_message(SidedMessage(side="side1", phase="phase",
                                    body="body", server_rx=1,
                                    msg_id="msgid"))
        msgs = self._messages(app)
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[-1]["body"], "body")

    def test_early_close(self):
        """
        One side opens a mailbox but closes it (explicitly) before any
        other side joins.
        """
        app = self._server.get_app("appid")
        name = app.allocate_nameplate("side1", 42)
        mbox = app.claim_nameplate(name, "side1", 0)
        m = app.open_mailbox(mbox, "side1", 0)
        m.close("side1", "mood", 1)


class Prune(unittest.TestCase):

    def _get_mailbox_updated(self, app, mbox_id):
        row = app._db.execute("SELECT * FROM `mailboxes` WHERE"
                              " `app_id`=? AND `id`=?",
                              (app._app_id, mbox_id)).fetchone()
        return row["updated"]

    def test_update(self):
        rv = make_server(create_channel_db(":memory:"))
        app = rv.get_app("appid")
        mbox_id = "mbox1"
        app.open_mailbox(mbox_id, "side1", 1)
        self.assertEqual(self._get_mailbox_updated(app, mbox_id), 1)

        mb = app.open_mailbox(mbox_id, "side2", 2)
        self.assertEqual(self._get_mailbox_updated(app, mbox_id), 2)

        sm = SidedMessage("side1", "phase", "body", 3, "msgid")
        mb.add_message(sm)
        self.assertEqual(self._get_mailbox_updated(app, mbox_id), 3)

    def test_apps(self):
        rv = make_server(create_channel_db(":memory:"))
        app = rv.get_app("appid")
        app.allocate_nameplate("side", 121)
        app.prune = mock.Mock()
        rv.prune_all_apps(now=123, old=122)
        self.assertEqual(app.prune.mock_calls, [mock.call(123, 122)])

    def test_nameplates(self):
        db = create_channel_db(":memory:")
        rv = make_server(db, blur_usage=3600)

        # timestamps <=50 are "old", >=51 are "new"
        #OLD = "old"; NEW = "new"
        #when = {OLD: 1, NEW: 60}
        new_nameplates = set()

        APPID = "appid"
        app = rv.get_app(APPID)

        # Exercise the first-vs-second newness tests
        app.claim_nameplate("np-1", "side1", 1)
        app.claim_nameplate("np-2", "side1", 1)
        app.claim_nameplate("np-2", "side2", 2)
        app.claim_nameplate("np-3", "side1", 60)
        new_nameplates.add("np-3")
        app.claim_nameplate("np-4", "side1", 1)
        app.claim_nameplate("np-4", "side2", 60)
        new_nameplates.add("np-4")
        app.claim_nameplate("np-5", "side1", 60)
        app.claim_nameplate("np-5", "side2", 61)
        new_nameplates.add("np-5")

        rv.prune_all_apps(now=123, old=50)

        nameplates = set([row["name"] for row in
                          db.execute("SELECT * FROM `nameplates`").fetchall()])
        self.assertEqual(new_nameplates, nameplates)
        mailboxes = set([row["id"] for row in
                         db.execute("SELECT * FROM `mailboxes`").fetchall()])
        self.assertEqual(len(new_nameplates), len(mailboxes))

    def test_mailboxes(self):
        db = create_channel_db(":memory:")
        rv = make_server(db, blur_usage=3600)

        # timestamps <=50 are "old", >=51 are "new"
        #OLD = "old"; NEW = "new"
        #when = {OLD: 1, NEW: 60}
        new_mailboxes = set()

        APPID = "appid"
        app = rv.get_app(APPID)

        # Exercise the first-vs-second newness tests
        app.open_mailbox("mb-11", "side1", 1)
        app.open_mailbox("mb-12", "side1", 1)
        app.open_mailbox("mb-12", "side2", 2)
        app.open_mailbox("mb-13", "side1", 60)
        new_mailboxes.add("mb-13")
        app.open_mailbox("mb-14", "side1", 1)
        app.open_mailbox("mb-14", "side2", 60)
        new_mailboxes.add("mb-14")
        app.open_mailbox("mb-15", "side1", 60)
        app.open_mailbox("mb-15", "side2", 61)
        new_mailboxes.add("mb-15")

        rv.prune_all_apps(now=123, old=50)

        mailboxes = set([row["id"] for row in
                         db.execute("SELECT * FROM `mailboxes`").fetchall()])
        self.assertEqual(new_mailboxes, mailboxes)

    def test_lots(self):
        OLD = "old"; NEW = "new"
        for nameplate in [False, True]:
            for mailbox in [OLD, NEW]:
                for has_listeners in [False, True]:
                    self.one(nameplate, mailbox, has_listeners)

    def test_one(self):
       # to debug specific problems found by test_lots
       self.one(None, "new", False)

    def one(self, nameplate, mailbox, has_listeners):
        desc = ("nameplate=%s, mailbox=%s, has_listeners=%s" %
                (nameplate, mailbox, has_listeners))
        log.msg(desc)

        db = create_channel_db(":memory:")
        rv = make_server(db, blur_usage=3600)
        APPID = "appid"
        app = rv.get_app(APPID)

        # timestamps <=50 are "old", >=51 are "new"
        OLD = "old"; NEW = "new"
        when = {OLD: 1, NEW: 60}
        nameplate_survives = False
        mailbox_survives = False

        mbid = "mbid"
        if nameplate:
            mbid = app.claim_nameplate("npid", "side1", when[mailbox])
        mb = app.open_mailbox(mbid, "side1", when[mailbox])

        # the pruning algorithm doesn't care about the age of messages,
        # because mailbox.updated is always updated each time we add a
        # message
        sm = SidedMessage("side1", "phase", "body", when[mailbox], "msgid")
        mb.add_message(sm)

        if has_listeners:
            mb.add_listener("handle", None, None)

        if (mailbox == NEW or has_listeners):
            if nameplate:
                nameplate_survives = True
            mailbox_survives = True
        messages_survive = mailbox_survives

        rv.prune_all_apps(now=123, old=50)

        nameplates = set([row["name"] for row in
                          db.execute("SELECT * FROM `nameplates`").fetchall()])
        self.assertEqual(nameplate_survives, bool(nameplates),
                         ("nameplate", nameplate_survives, nameplates, desc))

        mailboxes = set([row["id"] for row in
                         db.execute("SELECT * FROM `mailboxes`").fetchall()])
        self.assertEqual(mailbox_survives, bool(mailboxes),
                         ("mailbox", mailbox_survives, mailboxes, desc))

        messages = set([row["msg_id"] for row in
                          db.execute("SELECT * FROM `messages`").fetchall()])
        self.assertEqual(messages_survive, bool(messages),
                         ("messages", messages_survive, messages, desc))


class Summary(unittest.TestCase):
    def test_mailbox(self):
        app = AppNamespace(None, None, None, False, None, True)
        # starts at time 1, maybe gets second open at time 3, closes at 5
        def s(rows, pruned=False):
            return app._summarize_mailbox(rows, 5, pruned)

        rows = [dict(added=1)]
        self.assertEqual(s(rows), Usage(1, None, 4, "lonely"))
        rows = [dict(added=1, mood="lonely")]
        self.assertEqual(s(rows), Usage(1, None, 4, "lonely"))
        rows = [dict(added=1, mood="errory")]
        self.assertEqual(s(rows), Usage(1, None, 4, "errory"))
        rows = [dict(added=1, mood=None)]
        self.assertEqual(s(rows, pruned=True), Usage(1, None, 4, "pruney"))
        rows = [dict(added=1, mood="happy")]
        self.assertEqual(s(rows, pruned=True), Usage(1, None, 4, "pruney"))

        rows = [dict(added=1, mood="happy"), dict(added=3, mood="happy")]
        self.assertEqual(s(rows), Usage(1, 2, 4, "happy"))

        rows = [dict(added=1, mood="errory"), dict(added=3, mood="happy")]
        self.assertEqual(s(rows), Usage(1, 2, 4, "errory"))

        rows = [dict(added=1, mood="happy"), dict(added=3, mood="errory")]
        self.assertEqual(s(rows), Usage(1, 2, 4, "errory"))

        rows = [dict(added=1, mood="scary"), dict(added=3, mood="happy")]
        self.assertEqual(s(rows), Usage(1, 2, 4, "scary"))

        rows = [dict(added=1, mood="scary"), dict(added=3, mood="errory")]
        self.assertEqual(s(rows), Usage(1, 2, 4, "scary"))

        rows = [dict(added=1, mood="happy"), dict(added=3, mood=None)]
        self.assertEqual(s(rows, pruned=True), Usage(1, 2, 4, "pruney"))
        rows = [dict(added=1, mood="happy"), dict(added=3, mood="happy")]
        self.assertEqual(s(rows, pruned=True), Usage(1, 2, 4, "pruney"))

        rows = [dict(added=1), dict(added=3), dict(added=4)]
        self.assertEqual(s(rows), Usage(1, 2, 4, "crowded"))

        rows = [dict(added=1), dict(added=3), dict(added=4)]
        self.assertEqual(s(rows, pruned=True), Usage(1, 2, 4, "crowded"))

    def test_nameplate(self):
        a = AppNamespace(None, None, None, False, None, True)
        # starts at time 1, maybe gets second open at time 3, closes at 5
        def s(rows, pruned=False):
            return a._summarize_nameplate_usage(rows, 5, pruned)

        rows = [dict(added=1)]
        self.assertEqual(s(rows), Usage(1, None, 4, "lonely"))
        rows = [dict(added=1), dict(added=3)]
        self.assertEqual(s(rows), Usage(1, 2, 4, "happy"))

        rows = [dict(added=1), dict(added=3)]
        self.assertEqual(s(rows, pruned=True), Usage(1, 2, 4, "pruney"))

        rows = [dict(added=1), dict(added=3), dict(added=4)]
        self.assertEqual(s(rows), Usage(1, 2, 4, "crowded"))

    def test_nameplate_disallowed(self):
        db = create_channel_db(":memory:")
        a = AppNamespace(db, None, None, False, "some_app_id", False)
        a.allocate_nameplate("side1", "123")
        self.assertEqual([], a.get_nameplate_ids())

    def test_nameplate_allowed(self):
        db = create_channel_db(":memory:")
        a = AppNamespace(db, None, None, False, "some_app_id", True)
        np = a.allocate_nameplate("side1", "321")
        self.assertEqual(set([np]), a.get_nameplate_ids())

    def test_blur(self):
        db = create_channel_db(":memory:")
        usage_db = create_usage_db(":memory:")
        rv = make_server(db, blur_usage=3600, usage_db=usage_db)
        APPID = "appid"
        app = rv.get_app(APPID)
        app.claim_nameplate("npid", "side1", 10) # start time is 10
        rv.prune_all_apps(now=123, old=50)
        # start time should be rounded to top of the hour (blur_usage=3600)
        row = usage_db.execute("SELECT * FROM `nameplates`").fetchone()
        self.assertEqual(row["started"], 0)

        app = rv.get_app(APPID)
        app.open_mailbox("mbid", "side1", 20) # start time is 20
        rv.prune_all_apps(now=123, old=50)
        row = usage_db.execute("SELECT * FROM `mailboxes`").fetchone()
        self.assertEqual(row["started"], 0)

    def test_no_blur(self):
        db = create_channel_db(":memory:")
        usage_db = create_usage_db(":memory:")
        rv = make_server(db, blur_usage=None, usage_db=usage_db)
        APPID = "appid"
        app = rv.get_app(APPID)
        app.claim_nameplate("npid", "side1", 10) # start time is 10
        rv.prune_all_apps(now=123, old=50)
        row = usage_db.execute("SELECT * FROM `nameplates`").fetchone()
        self.assertEqual(row["started"], 10)

        usage_db.execute("DELETE FROM `mailboxes`")
        usage_db.commit()
        app = rv.get_app(APPID)
        app.open_mailbox("mbid", "side1", 20) # start time is 20
        rv.prune_all_apps(now=123, old=50)
        row = usage_db.execute("SELECT * FROM `mailboxes`").fetchone()
        self.assertEqual(row["started"], 20)

## class DumpStats(unittest.TestCase):
##     def test_nostats(self):
##         rs = easy_relay()
##         # with no ._stats_file, this should do nothing
##         rs.dump_stats(1, 1)

##     def test_empty(self):
##         basedir = self.mktemp()
##         os.mkdir(basedir)
##         fn = os.path.join(basedir, "stats.json")
##         rs = easy_relay(stats_file=fn)
##         now = 1234
##         validity = 500
##         rs.dump_stats(now, validity)
##         with open(fn, "rb") as f:
##             data_bytes = f.read()
##         data = json.loads(data_bytes.decode("utf-8"))
##         self.assertEqual(data["created"], now)
##         self.assertEqual(data["valid_until"], now+validity)
##         self.assertEqual(data["rendezvous"]["all_time"]["mailboxes_total"], 0)

class Startup(unittest.TestCase):
    @mock.patch('wormhole_mailbox_server.server.log')
    def test_empty(self, fake_log):
        db = create_channel_db(":memory:")
        s = make_server(db, allow_list=False)
        s.startService()
        try:
            logs = '\n'.join([call[1][0] for call in fake_log.mock_calls])
            self.assertIn('listing of allocated nameplates disallowed', logs)
        finally:
            s.stopService()

    @mock.patch('wormhole_mailbox_server.server.log')
    def test_allow_list(self, fake_log):
        db = create_channel_db(":memory:")
        s = make_server(db, allow_list=True)
        s.startService()
        try:
            logs = '\n'.join([call[1][0] for call in fake_log.mock_calls])
            self.assertNotIn('listing of allocated nameplates disallowed', logs)
        finally:
            s.stopService()

    @mock.patch('wormhole_mailbox_server.server.log')
    def test_blur_usage(self, fake_log):
        db = create_channel_db(":memory:")
        s = make_server(db, blur_usage=60, allow_list=True)
        s.startService()
        try:
            logs = '\n'.join([call[1][0] for call in fake_log.mock_calls])
            self.assertNotIn('listing of allocated nameplates disallowed', logs)
            self.assertIn('blurring access times to 60 seconds', logs)
        finally:
            s.stopService()

class MakeServer(unittest.TestCase):
    def test_welcome_empty(self):
        db = create_channel_db(":memory:")
        s = make_server(db)
        self.assertEqual(s.get_welcome(), {})

    def test_welcome_error(self):
        db = create_channel_db(":memory:")
        s = make_server(db, signal_error="error!")
        self.assertEqual(s.get_welcome(), {"error": "error!"})

    def test_welcome_advertise_version(self):
        db = create_channel_db(":memory:")
        s = make_server(db, advertise_version="version")
        self.assertEqual(s.get_welcome(), {"current_cli_version": "version"})

    def test_welcome_message_of_the_day(self):
        db = create_channel_db(":memory:")
        s = make_server(db, welcome_motd="hello world")
        self.assertEqual(s.get_welcome(), {"motd": "hello world"})

# exercise _find_available_nameplate_id failing
# exercise CrowdedError
# exercise double free_mailbox
# exercise _summarize_mailbox = quiet (0 sides)
# exercise AppNamespace._shutdown
#  so Server.stopService
## test blur_usage/not on Server
## test make_server(signal_error=)
## exercise dump_stats (with/without usagedb)

