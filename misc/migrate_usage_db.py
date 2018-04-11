"""Migrate the usage data from the old bundled Mailbox Server database.

The magic-wormhole package used to include both servers (Rendezvous and
Transit). "wormhole server" started both of these, and used the
"relay.sqlite" database to store both immediate server state and long-term
usage data.

These were split out to their own packages: version 0.11 omitted the Transit
Relay, and 0.12 removed the Mailbox Server in favor of the new
"magic-wormhole-mailbox-server" distribution.

This script reads the long-term usage data from the pre-0.12 wormhole-server
relay.sqlite, and copies it into a new "usage.sqlite" database in the current
directory.

It will refuse to touch an existing "usage.sqlite" file.

The resuting "usage.sqlite" should be passed into --usage-db=, e.g. "twist
wormhole-mailbox --usage-db=.../PATH/TO/usage.sqlite".
"""

from __future__ import unicode_literals, print_function
import sys
from wormhole_mailbox_server.database import open_existing_db, create_usage_db

source_fn = sys.argv[1]
source_db = open_existing_db(source_fn)
target_db = create_usage_db("usage.sqlite")

num_nameplate_rows = 0
for row in source_db.execute("SELECT * FROM `nameplate_usage`"
                             " ORDER BY `started`").fetchall():
    target_db.execute("INSERT INTO `nameplates`"
                      " (`app_id`, `started`, `waiting_time`,"
                      "  `total_time`, `result`)"
                      " VALUES(?,?,?,?,?)",
                      (row["app_id"], row["started"], row["waiting_time"],
                       row["total_time"], row["result"]))
    num_nameplate_rows += 1


num_mailbox_rows = 0
for row in source_db.execute("SELECT * FROM `mailbox_usage`"
                             " ORDER BY `started`").fetchall():
    target_db.execute("INSERT INTO `mailboxes`"
                      " (`app_id`, `for_nameplate`,"
                      " `started`, `total_time`, `waiting_time`,"
                      "  `result`)"
                      " VALUES(?,?,?,?,?,?)",
                      (row["app_id"], row["for_nameplate"],
                       row["started"], row["total_time"], row["waiting_time"],
                       row["result"]))
    num_mailbox_rows += 1

target_db.execute("INSERT INTO `current`"
                  " (`rebooted`, `updated`, `blur_time`,"
                  "  `connections_websocket`)"
                  " VALUES(?,?,?,?)",
                  (0, 0, 0, 0))
target_db.commit()

print("usage database migrated (%d+%d rows) into 'usage.sqlite'" % (num_nameplate_rows, num_mailbox_rows))
sys.exit(0)
