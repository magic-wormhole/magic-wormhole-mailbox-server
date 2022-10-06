from __future__ import print_function, unicode_literals
import os, random, base64
from collections import namedtuple
from twisted.python import log
from twisted.application import service

def generate_mailbox_id():
    return base64.b32encode(os.urandom(8)).lower().strip(b"=").decode("ascii")

class CrowdedError(Exception):
    pass
class ReclaimedError(Exception):
    pass

Usage = namedtuple("Usage", ["started", "waiting_time", "total_time", "result"])
TransitUsage = namedtuple("TransitUsage",
                          ["started", "waiting_time", "total_time",
                           "total_bytes", "result"])

SidedMessage = namedtuple("SidedMessage", ["side", "phase", "body",
                                           "server_rx", "msg_id"])

class Mailbox:
    def __init__(self, app, db, usage_db, app_id, mailbox_id):
        self._app = app
        self._db = db
        self._usage_db = usage_db
        self._app_id = app_id
        self._mailbox_id = mailbox_id
        self._listeners = {} # handle -> (send_f, stop_f)
        # "handle" is a hashable object, for deregistration
        # send_f() takes a JSONable object, stop_f() has no args

    def open(self, side, when):
        # requires caller to db.commit()
        assert isinstance(side, type("")), type(side)
        db = self._db

        already = db.execute("SELECT * FROM `mailbox_sides`"
                             " WHERE `mailbox_id`=? AND `side`=?",
                             (self._mailbox_id, side)).fetchone()
        if not already:
            db.execute("INSERT INTO `mailbox_sides`"
                       " (`mailbox_id`, `opened`, `side`, `added`)"
                       " VALUES(?,?,?,?)",
                       (self._mailbox_id, True, side, when))
        # We accept re-opening a mailbox which a side previously closed,
        # unlike claim_nameplate(), which forbids any side from re-claiming a
        # nameplate which they previously released. (Nameplates forbid this
        # because the act of claiming a nameplate for the first time causes a
        # new mailbox to be created, which should only happen once).
        # Mailboxes have their own distinct objects (to manage
        # subscriptions), so closing one which was already closed requires
        # making a new object, which works by calling open() just before
        # close(). We really do want to support re-closing closed mailboxes,
        # because this enables intermittently-connected clients, who remember
        # sending a 'close' but aren't sure whether it was received or not,
        # then get shut down. Those clients will wake up and re-send the
        # 'close', until they receive the 'closed' ack message.

        self._touch(when)
        db.commit() # XXX: reconcile the need for this with the comment above

    def _touch(self, when):
        self._db.execute("UPDATE `mailboxes` SET `updated`=? WHERE `id`=?",
                         (when, self._mailbox_id))

    def get_messages(self):
        messages = []
        db = self._db
        for row in db.execute("SELECT * FROM `messages`"
                              " WHERE `app_id`=? AND `mailbox_id`=?"
                              " ORDER BY `server_rx` ASC",
                              (self._app_id, self._mailbox_id)).fetchall():
            sm = SidedMessage(side=row["side"], phase=row["phase"],
                              body=row["body"], server_rx=row["server_rx"],
                              msg_id=row["msg_id"])
            messages.append(sm)
        return messages

    def add_listener(self, handle, send_f, stop_f):
        #log.msg("add_listener", self._mailbox_id, handle)
        self._listeners[handle] = (send_f, stop_f)
        #log.msg(" added", len(self._listeners))
        return self.get_messages()

    def remove_listener(self, handle):
        #log.msg("remove_listener", self._mailbox_id, handle)
        self._listeners.pop(handle, None)
        #log.msg(" removed", len(self._listeners))

    def has_listeners(self):
        return bool(self._listeners)

    def count_listeners(self):
        return len(self._listeners)

    def broadcast_message(self, sm):
        for (send_f, stop_f) in self._listeners.values():
            send_f(sm)

    def _add_message(self, sm):
        self._db.execute("INSERT INTO `messages`"
                         " (`app_id`, `mailbox_id`, `side`, `phase`,  `body`,"
                         "  `server_rx`, `msg_id`)"
                         " VALUES (?,?,?,?,?, ?,?)",
                         (self._app_id, self._mailbox_id, sm.side,
                          sm.phase, sm.body, sm.server_rx, sm.msg_id))
        self._touch(sm.server_rx)
        self._db.commit()

    def add_message(self, sm):
        assert isinstance(sm, SidedMessage)
        self._add_message(sm)
        self.broadcast_message(sm)

    def close(self, side, mood, when):
        assert isinstance(side, type("")), type(side)
        db = self._db
        row = db.execute("SELECT * FROM `mailboxes`"
                         " WHERE `app_id`=? AND `id`=?",
                         (self._app_id, self._mailbox_id)).fetchone()
        if not row:
            return
        for_nameplate = row["for_nameplate"]

        row = db.execute("SELECT * FROM `mailbox_sides`"
                         " WHERE `mailbox_id`=? AND `side`=?",
                         (self._mailbox_id, side)).fetchone()
        if not row:
            return
        db.execute("UPDATE `mailbox_sides` SET `opened`=?, `mood`=?"
                   " WHERE `mailbox_id`=? AND `side`=?",
                   (False, mood, self._mailbox_id, side))
        db.commit()

        # are any sides still open?
        side_rows = db.execute("SELECT * FROM `mailbox_sides`"
                               " WHERE `mailbox_id`=?",
                               (self._mailbox_id,)).fetchall()
        if any([sr["opened"] for sr in side_rows]):
            return

        # nope. delete and summarize

        # if the nameplate is still allocated we'll get a foreign-key
        # failure when trying to delete the mailbox, so get rid of
        # those first
        db.execute("DELETE FROM `nameplate_sides` WHERE `side`=?",
                   (side,))
        db.execute("DELETE FROM `nameplates` WHERE `mailbox_id`=?",
                   (self._mailbox_id,))
        # remove mailbox content
        db.execute("DELETE FROM `messages` WHERE `mailbox_id`=?",
                   (self._mailbox_id,))
        db.execute("DELETE FROM `mailbox_sides` WHERE `mailbox_id`=?",
                   (self._mailbox_id,))
        db.execute("DELETE FROM `mailboxes` WHERE `id`=?", (self._mailbox_id,))
        if self._usage_db:
            self._app._summarize_mailbox_and_store(for_nameplate, side_rows,
                                                when, pruned=False)
            self._usage_db.commit()
        db.commit()
        # Shut down any listeners, just in case they're still lingering
        # around.
        for (send_f, stop_f) in self._listeners.values():
            stop_f()
        self._listeners = {}
        self._app.free_mailbox(self._mailbox_id)

    def _shutdown(self):
        # used at test shutdown to accelerate client disconnects
        for (send_f, stop_f) in self._listeners.values():
            stop_f()
        self._listeners = {}


class AppNamespace(object):

    def __init__(self, db, usage_db, blur_usage, log_requests, app_id,
                 allow_list):
        self._db = db
        self._usage_db = usage_db
        self._blur_usage = blur_usage
        self._log_requests = log_requests
        self._app_id = app_id
        self._mailboxes = {}
        self._allow_list = allow_list

    def log_client_version(self, server_rx, side, client_version):
        if self._blur_usage:
            server_rx = self._blur_usage * (server_rx // self._blur_usage)
        implementation = client_version[0]
        version = client_version[1]
        if self._usage_db:
            self._usage_db.execute("INSERT INTO `client_versions`"
                                   " (`app_id`, `side`, `connect_time`,"
                                   "  `implementation`, `version`)"
                                   " VALUES(?,?,?,?,?)",
                                   (self._app_id, side, server_rx,
                                    implementation, version))
            self._usage_db.commit()

    def get_nameplate_ids(self):
        if not self._allow_list:
            return []
        return self._get_nameplate_ids()

    def _get_nameplate_ids(self):
        db = self._db
        # TODO: filter this to numeric ids?
        c = db.execute("SELECT DISTINCT `name` FROM `nameplates`"
                       " WHERE `app_id`=?", (self._app_id,))
        return set([row["name"] for row in c.fetchall()])

    def _find_available_nameplate_id(self):
        claimed = self._get_nameplate_ids()
        for size in range(1,4): # stick to 1-999 for now
            available = set()
            for id_int in range(10**(size-1), 10**size):
                id = "%d" % id_int
                if id not in claimed:
                    available.add(id)
            if available:
                return random.choice(list(available))
        # ouch, 999 currently claimed. Try random ones for a while.
        for tries in range(1000):
            id_int = random.randrange(1000, 1000*1000)
            id = "%d" % id_int
            if id not in claimed:
                return id
        raise ValueError("unable to find a free nameplate-id")

    def allocate_nameplate(self, side, when):
        nameplate_id = self._find_available_nameplate_id()
        mailbox_id = self.claim_nameplate(nameplate_id, side, when)
        del mailbox_id # ignored, they'll learn it from claim()
        return nameplate_id

    def claim_nameplate(self, name, side, when):
        # when we're done:
        # * there will be one row for the nameplate
        #  * there will be one 'side' attached to it, with claimed=True
        # * a mailbox id and mailbox row will be created
        #  * a mailbox 'side' will be attached, with opened=True
        assert isinstance(name, type("")), type(name)
        assert isinstance(side, type("")), type(side)
        db = self._db
        row = db.execute("SELECT * FROM `nameplates`"
                         " WHERE `app_id`=? AND `name`=?",
                         (self._app_id, name)).fetchone()
        if not row:
            if self._log_requests:
                log.msg("creating nameplate#%s for app_id %s" %
                        (name, self._app_id))
            mailbox_id = generate_mailbox_id()
            self._add_mailbox(mailbox_id, True, side, when) # ensure row exists
            sql = ("INSERT INTO `nameplates`"
                   " (`app_id`, `name`, `mailbox_id`)"
                   " VALUES(?,?,?)")
            npid = db.execute(sql, (self._app_id, name, mailbox_id)
                              ).lastrowid
        else:
            npid = row["id"]
            mailbox_id = row["mailbox_id"]

        row = db.execute("SELECT * FROM `nameplate_sides`"
                         " WHERE `nameplates_id`=? AND `side`=?",
                         (npid, side)).fetchone()
        if not row:
            db.execute("INSERT INTO `nameplate_sides`"
                       " (`nameplates_id`, `claimed`, `side`, `added`)"
                       " VALUES(?,?,?,?)",
                       (npid, True, side, when))
        else:
            if not row["claimed"]:
                raise ReclaimedError("you cannot re-claim a nameplate that your side previously released")
            # since that might cause a new mailbox to be allocated
        db.commit()

        self.open_mailbox(mailbox_id, side, when) # may raise CrowdedError
        rows = db.execute("SELECT * FROM `nameplate_sides`"
                          " WHERE `nameplates_id`=?", (npid,)).fetchall()
        if len(rows) > 2:
            # this line will probably never get hit: any crowding is noticed
            # on mailbox_sides first, inside open_mailbox()
            raise CrowdedError("too many sides have claimed this nameplate")
        return mailbox_id

    def release_nameplate(self, name, side, when):
        # when we're done:
        # * the 'claimed' flag will be cleared on the nameplate_sides row
        # * if the nameplate is now unused (no claimed sides):
        #  * a usage record will be added
        #  * the nameplate row will be removed
        #  * the nameplate sides will be removed
        assert isinstance(name, type("")), type(name)
        assert isinstance(side, type("")), type(side)
        db = self._db
        np_row = db.execute("SELECT * FROM `nameplates`"
                            " WHERE `app_id`=? AND `name`=?",
                            (self._app_id, name)).fetchone()
        if not np_row:
            return
        npid = np_row["id"]
        row = db.execute("SELECT * FROM `nameplate_sides`"
                         " WHERE `nameplates_id`=? AND `side`=?",
                         (npid, side)).fetchone()
        if not row:
            return
        db.execute("UPDATE `nameplate_sides` SET `claimed`=?"
                   " WHERE `nameplates_id`=? AND `side`=?",
                   (False, npid, side))
        db.commit()

        # now, are there any remaining claims?
        side_rows = db.execute("SELECT * FROM `nameplate_sides`"
                               " WHERE `nameplates_id`=?",
                               (npid,)).fetchall()
        claims = [1 for sr in side_rows if sr["claimed"]]
        if claims:
            return
        # delete and summarize
        db.execute("DELETE FROM `nameplate_sides` WHERE `nameplates_id`=?",
                   (npid,))
        db.execute("DELETE FROM `nameplates` WHERE `id`=?", (npid,))
        if self._usage_db:
            self._summarize_nameplate_and_store(side_rows, when, pruned=False)
            self._usage_db.commit()
        db.commit()

    def _summarize_nameplate_and_store(self, side_rows, delete_time, pruned):
        # requires caller to self._usage_db.commit()
        u = self._summarize_nameplate_usage(side_rows, delete_time, pruned)
        self._usage_db.execute("INSERT INTO `nameplates`"
                            " (`app_id`,"
                            " `started`, `total_time`, `waiting_time`, `result`)"
                            " VALUES (?, ?,?,?,?)",
                            (self._app_id,
                            u.started, u.total_time, u.waiting_time, u.result))

    def _summarize_nameplate_usage(self, side_rows, delete_time, pruned):
        times = sorted([row["added"] for row in side_rows])
        started = times[0]
        if self._blur_usage:
            started = self._blur_usage * (started // self._blur_usage)
        waiting_time = None
        if len(times) > 1:
            waiting_time = times[1] - times[0]
        total_time = delete_time - times[0]
        result = "lonely"
        if len(times) == 2:
            result = "happy"
        if pruned:
            result = "pruney"
        if len(times) > 2:
            result = "crowded"
        return Usage(started=started, waiting_time=waiting_time,
                     total_time=total_time, result=result)

    def _add_mailbox(self, mailbox_id, for_nameplate, side, when):
        assert isinstance(mailbox_id, type("")), type(mailbox_id)
        db = self._db
        row = db.execute("SELECT * FROM `mailboxes`"
                         " WHERE `app_id`=? AND `id`=?",
                         (self._app_id, mailbox_id)).fetchone()
        if not row:
            self._db.execute("INSERT INTO `mailboxes`"
                             " (`app_id`, `id`, `for_nameplate`, `updated`)"
                             " VALUES(?,?,?,?)",
                             (self._app_id, mailbox_id, for_nameplate, when))
            # we don't need a commit here, because mailbox.open() only
            # does SELECT FROM `mailbox_sides`, not from `mailboxes`

    def open_mailbox(self, mailbox_id, side, when):
        assert isinstance(mailbox_id, type("")), type(mailbox_id)
        self._add_mailbox(mailbox_id, False, side, when) # ensure row exists
        db = self._db
        if not mailbox_id in self._mailboxes: # ensure Mailbox object exists
            if self._log_requests:
                log.msg("spawning #%s for app_id %s" % (mailbox_id,
                                                        self._app_id))
            self._mailboxes[mailbox_id] = Mailbox(self,
                                                  self._db, self._usage_db,
                                                  self._app_id, mailbox_id)
        mailbox = self._mailboxes[mailbox_id]

        # delegate to mailbox.open() to add a row to mailbox_sides, and
        # update the mailbox.updated timestamp
        mailbox.open(side, when)
        db.commit()
        rows = db.execute("SELECT * FROM `mailbox_sides`"
                          " WHERE `mailbox_id`=?",
                          (mailbox_id,)).fetchall()
        if len(rows) > 2:
            raise CrowdedError("too many sides have opened this mailbox")
        return mailbox

    def free_mailbox(self, mailbox_id):
        # called from Mailbox.delete_and_summarize(), which deletes any
        # messages

        if mailbox_id in self._mailboxes:
            self._mailboxes.pop(mailbox_id)
        #if self._log_requests:
        #    log.msg("freed+killed #%s, now have %d DB mailboxes, %d live" %
        #            (mailbox_id, len(self.get_claimed()), len(self._mailboxes)))

    def _summarize_mailbox_and_store(self, for_nameplate, side_rows,
                                     delete_time, pruned):
        db = self._usage_db
        u = self._summarize_mailbox(side_rows, delete_time, pruned)
        db.execute("INSERT INTO `mailboxes`"
                   " (`app_id`, `for_nameplate`,"
                   "  `started`, `total_time`, `waiting_time`, `result`)"
                   " VALUES (?,?, ?,?,?,?)",
                   (self._app_id, for_nameplate,
                    u.started, u.total_time, u.waiting_time, u.result))

    def _summarize_mailbox(self, side_rows, delete_time, pruned):
        times = sorted([row["added"] for row in side_rows])
        started = times[0]
        if self._blur_usage:
            started = self._blur_usage * (started // self._blur_usage)
        waiting_time = None
        if len(times) > 1:
            waiting_time = times[1] - times[0]
        total_time = delete_time - times[0]

        num_sides = len(times)
        if num_sides == 0:
            result = "quiet"
        elif num_sides == 1:
            result = "lonely"
        else:
            result = "happy"

        # "mood" is only recorded at close()
        moods = [row["mood"] for row in side_rows if row.get("mood")]
        if "lonely" in moods:
            result = "lonely"
        if "errory" in moods:
            result = "errory"
        if "scary" in moods:
            result = "scary"
        if pruned:
            result = "pruney"
        if num_sides > 2:
            result = "crowded"

        return Usage(started=started, waiting_time=waiting_time,
                     total_time=total_time, result=result)

    def prune(self, now, old):
        # The pruning check runs every 10 minutes, and "old" is defined to be
        # 11 minutes ago (unit tests can use different values). The client is
        # allowed to disconnect for up to 9 minutes without losing the
        # channel (nameplate, mailbox, and messages).

        # Each time a client does something, the mailbox.updated field is
        # updated with the current timestamp. If a client is subscribed to
        # the mailbox when pruning check runs, the "updated" field is also
        # updated. After that check, if the "updated" field is "old", the
        # channel is deleted.

        # For now, pruning is logged even if log_requests is False, to debug
        # the pruning process, and since pruning is triggered by a timer
        # instead of by user action. It does reveal which mailboxes were
        # present when the pruning process began, though, so in the log run
        # it should do less logging.
        log.msg(" prune begins (%s)" % self._app_id)
        db = self._db
        modified = False

        for mailbox in self._mailboxes.values():
            if mailbox.has_listeners():
                log.msg("touch %s because listeners" % mailbox._mailbox_id)
                mailbox._touch(now)
        db.commit() # make sure the updates are visible below

        new_mailboxes = set()
        old_mailboxes = set()
        for row in db.execute("SELECT * FROM `mailboxes` WHERE `app_id`=?",
                              (self._app_id,)).fetchall():
            mailbox_id = row["id"]
            log.msg("  1: age=%s, old=%s, %s" %
                    (now - row["updated"], now - old, mailbox_id))
            if row["updated"] > old:
                new_mailboxes.add(mailbox_id)
            else:
                old_mailboxes.add(mailbox_id)
        log.msg(" 2: mailboxes:", new_mailboxes, old_mailboxes)

        old_nameplates = set()
        for row in db.execute("SELECT * FROM `nameplates` WHERE `app_id`=?",
                              (self._app_id,)).fetchall():
            npid = row["id"]
            mailbox_id = row["mailbox_id"]
            if mailbox_id in old_mailboxes:
                old_nameplates.add(npid)
        log.msg(" 3: old_nameplates dbids", old_nameplates)

        for npid in old_nameplates:
            log.msg("  deleting nameplate with dbid", npid)
            side_rows = db.execute("SELECT * FROM `nameplate_sides`"
                                   " WHERE `nameplates_id`=?",
                                   (npid,)).fetchall()
            db.execute("DELETE FROM `nameplate_sides` WHERE `nameplates_id`=?",
                       (npid,))
            db.execute("DELETE FROM `nameplates` WHERE `id`=?", (npid,))
            if self._usage_db:
                self._summarize_nameplate_and_store(side_rows, now, pruned=True)
            modified = True

        # delete all messages for old mailboxes
        # delete all old mailboxes

        for mailbox_id in old_mailboxes:
            log.msg("  deleting mailbox", mailbox_id)
            row = db.execute("SELECT * FROM `mailboxes`"
                             " WHERE `id`=?", (mailbox_id,)).fetchone()
            for_nameplate = row["for_nameplate"]
            side_rows = db.execute("SELECT * FROM `mailbox_sides`"
                                   " WHERE `mailbox_id`=?",
                                   (mailbox_id,)).fetchall()
            db.execute("DELETE FROM `messages` WHERE `mailbox_id`=?",
                       (mailbox_id,))
            db.execute("DELETE FROM `mailbox_sides` WHERE `mailbox_id`=?",
                       (mailbox_id,))
            db.execute("DELETE FROM `mailboxes` WHERE `id`=?",
                       (mailbox_id,))
            if self._usage_db:
                self._summarize_mailbox_and_store(for_nameplate, side_rows,
                                                  now, pruned=True)
            modified = True

        if modified:
            db.commit()
            if self._usage_db:
                self._usage_db.commit()
        in_use = bool(self._mailboxes)
        log.msg("  prune complete, modified=%s, in_use=%s" % (modified, in_use))
        return in_use

    def count_listeners(self):
        return sum(mailbox.count_listeners()
                   for mailbox in self._mailboxes.values())

    def _shutdown(self):
        for channel in self._mailboxes.values():
            channel._shutdown()


class Server(service.MultiService):
    def __init__(self, db, allow_list, welcome,
                 blur_usage, usage_db=None, log_file=None):
        service.MultiService.__init__(self)
        self._db = db
        self._allow_list = allow_list
        self._welcome = welcome
        self._blur_usage = blur_usage
        self._log_requests = blur_usage is None
        self._usage_db = usage_db
        self._log_file = log_file
        self._apps = {}

    def get_welcome(self):
        return self._welcome
    def get_log_requests(self):
        return self._log_requests

    def get_app(self, app_id):
        assert isinstance(app_id, type(""))
        if not app_id in self._apps:
            if self._log_requests:
                log.msg("spawning app_id %s" % (app_id,))
            self._apps[app_id] = AppNamespace(
                self._db,
                self._usage_db,
                self._blur_usage,
                self._log_requests,
                app_id,
                self._allow_list,
            )
        return self._apps[app_id]

    def get_all_apps(self):
        apps = set()
        for row in self._db.execute("SELECT DISTINCT `app_id`"
                                    " FROM `nameplates`").fetchall():
            apps.add(row["app_id"])
        for row in self._db.execute("SELECT DISTINCT `app_id`"
                                    " FROM `mailboxes`").fetchall():
            apps.add(row["app_id"])
        for row in self._db.execute("SELECT DISTINCT `app_id`"
                                    " FROM `messages`").fetchall():
            apps.add(row["app_id"])
        return apps

    def prune_all_apps(self, now, old):
        # As with AppNamespace.prune_old_mailboxes, we log for now.
        log.msg("beginning app prune")
        for app_id in sorted(self.get_all_apps()):
            log.msg(" app prune checking %r" % (app_id,))
            app = self.get_app(app_id)
            in_use = app.prune(now, old)
            if not in_use:
                del self._apps[app_id]
        log.msg("app prune ends, %d apps" % len(self._apps))

    def dump_stats(self, now, rebooted):
        if not self._usage_db:
            return
        # write everything to self._usage_db

        # Most of our current-status state is recorded in the channel_db, and
        # our historical state goes into the usage_db. Both are updated each
        # time something changes, so stats monitors can just read things out
        # from there. The one bit of runtime state that isn't recorded each
        # time is the number of connected clients, which will differ from the
        # number of live "sides" briefly after they disconnect but before the
        # mailbox is closed.

        connections = sum(app.count_listeners()
                          for app in self._apps.values())
        # TODO: this is all connections, not just the websocket ones. We don't
        # have non-websocket connections yet, but when we add them, this needs
        # to be updated. Probably by asking the WebSocketServerFactory to count
        # them.
        self._usage_db.execute("DELETE FROM `current`")
        self._usage_db.execute("INSERT INTO `current`"
                               " (`rebooted`, `updated`, `blur_time`,"
                               "  `connections_websocket`)"
                               " VALUES(?,?,?,?)",
                               (rebooted, now, self._blur_usage, connections))
        self._usage_db.commit()

        # current status: expected to be zero most of the time
        #c["nameplates_total"] = q("SELECT COUNT() FROM `nameplates`")
        # TODO: nameplates with only one side (most of them)
        # TODO: nameplates with two sides (very fleeting)
        # TODO: nameplates with three or more sides (crowded, unlikely)
        #c["mailboxes_total"] = q("SELECT COUNT() FROM `mailboxes`")
        # TODO: mailboxes with only one side (most of them)
        # TODO: mailboxes with two sides (somewhat fleeting, in-transit)
        # TODO: mailboxes with three or more sides (unlikely)
        #c["messages_total"] = q("SELECT COUNT() FROM `messages`")

        # recent timings (last 100 operations)
        # TODO: median/etc of nameplate.total_time
        # TODO: median/etc of mailbox.waiting_time (should be the same)
        # TODO: median/etc of mailbox.total_time

        # other
        # TODO: mailboxes without nameplates (needs new DB schema)

    def startService(self):
        service.MultiService.startService(self)
        log.msg("Wormhole relay server running")
        if self._blur_usage:
            log.msg("blurring access times to %d seconds" % self._blur_usage)
            #log.msg("not logging HTTP requests")
        else:
            log.msg("not blurring access times")
        if not self._allow_list:
            log.msg("listing of allocated nameplates disallowed")

    def stopService(self):
        # This forcibly boots any clients that are still connected, which
        # helps with unit tests that use threads for both clients. One client
        # hits an exception, which terminates the test (and .tearDown calls
        # stopService on the relay), but the other client (in its thread) is
        # still waiting for a message. By killing off all connections, that
        # other client gets an error, and exits promptly.
        for app in self._apps.values():
            app._shutdown()
        return service.MultiService.stopService(self)

def make_server(db, allow_list=True,
                advertise_version=None,
                signal_error=None,
                blur_usage=None,
                usage_db=None,
                log_file=None,
                welcome_motd=None,
                ):
    if blur_usage:
        log.msg("blurring access times to %d seconds" % blur_usage)
    else:
        log.msg("not blurring access times")

    welcome = dict()
    if welcome_motd is not None:
        # adding .motd will cause all clients to display the message,
        # then keep running normally
        welcome["motd"] = str(welcome_motd)

    if advertise_version:
        # The primary (python CLI) implementation will emit a message if
        # its version does not match this key. If/when we have
        # distributions which include older version, but we still expect
        # them to be compatible, stop sending this key.
        welcome["current_cli_version"] = advertise_version

    if signal_error:
        welcome["error"] = signal_error

    return Server(db, allow_list=allow_list, welcome=welcome,
                  blur_usage=blur_usage, usage_db=usage_db, log_file=log_file)
