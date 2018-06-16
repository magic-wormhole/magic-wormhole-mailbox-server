"""Migrate the channel data from the old bundled Mailbox Server database.

The magic-wormhole package used to include both servers (Rendezvous and
Transit). "wormhole server" started both of these, and used the
"relay.sqlite" database to store both immediate server state and long-term
usage data.

These were split out to their own packages: version 0.11 omitted the Transit
Relay, and 0.12 removed the Mailbox Server in favor of the new
"magic-wormhole-mailbox-server" distribution.

This script reads the short-term channel data from the pre-0.12
wormhole-server relay.sqlite, and copies it into a new "relay.sqlite"
database in the current directory.

It will refuse to touch an existing "relay.sqlite" file.

The resuting "relay.sqlite" should be passed into --channel-db=, e.g. "twist
wormhole-mailbox --channel-db=.../PATH/TO/relay.sqlite". However in most
cases you can just store it in the default location of "./relay.sqlite" and
omit the --channel-db= argument.

Note that an idle server will have no channel data, so you could instead just
wait for the server to be empty (sqlite3 relay.sqlite message |grep INSERT).
"""

from __future__ import unicode_literals, print_function
import sys
from wormhole_mailbox_server.database import (open_existing_db,
                                              create_channel_db)

source_fn = sys.argv[1]
source_db = open_existing_db(source_fn)
target_db = create_channel_db("relay.sqlite")

num_rows = 0

for row in source_db.execute("SELECT * FROM `mailboxes`").fetchall():
    target_db.execute("INSERT INTO `mailboxes`"
                      " (`app_id`, `id`, `updated`, `for_nameplate`)"
                      " VALUES(?,?,?,?)",
                      (row["app_id"], row["id"], row["updated"],
                       row["for_nameplate"]))
    num_rows += 1

for row in source_db.execute("SELECT * FROM `mailbox_sides`").fetchall():
    target_db.execute("INSERT INTO `mailbox_sides`"
                      " (`mailbox_id`, `opened`, `side`, `added`, `mood`)"
                      " VALUES(?,?,?,?,?)",
                      (row["mailbox_id"], row["opened"], row["side"],
                       row["added"], row["mood"]))
    num_rows += 1

for row in source_db.execute("SELECT * FROM `nameplates`").fetchall():
    target_db.execute("INSERT INTO `nameplates`"
                      " (`id`, `app_id`, `name`, `mailbox_id`, `request_id`)"
                      " VALUES(?,?,?,?,?)",
                      (row["id"], row["app_id"], row["name"],
                       row["mailbox_id"], row["request_id"]))
    num_rows += 1

for row in source_db.execute("SELECT * FROM `nameplate_sides`").fetchall():
    target_db.execute("INSERT INTO `nameplate_sides`"
                      " (`nameplates_id`, `claimed`, `side`, `added`)"
                      " VALUES(?,?,?,?)",
                      (row["nameplates_id"], row["claimed"], row["side"],
                       row["added"]))
    num_rows += 1

for row in source_db.execute("SELECT * FROM `messages`").fetchall():
    target_db.execute("INSERT INTO `messages`"
                      " (`app_id`, `mailbox_id`, `side`, `phase`, `body`, "
                      "  `server_rx`, `msg_id`)"
                      " VALUES(?,?,?,?,?,?,?)",
                      (row["app_id"], row["mailbox_id"], row["side"],
                       row["phase"], row["body"],
                       row["server_rx"], row["msg_id"]))
    num_rows += 1
target_db.commit()

print("channel database migrated (%d rows) into 'relay.sqlite'" % num_rows)
sys.exit(0)
