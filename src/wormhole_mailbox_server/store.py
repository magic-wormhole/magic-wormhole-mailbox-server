"""Persistence layer for the mailbox server.

The Twisted/WebSocket protocol code must not contain SQL. All database
access goes through the small store classes defined here:

* :class:`MailboxStore` owns the channel database (mailboxes, nameplates,
  messages, address-id generations, and connection bookkeeping).
* :class:`UsageStore` owns the optional usage database (operational
  history).
* :class:`AddressIDStore` owns the optional address-id database.

For now these stores wrap the existing DB-API connections, so behavior is
identical to the previous direct ``sqlite3`` calls. The connection attribute
is an escape hatch for schema-management code and tests only; protocol code
should use the methods below.
"""


def _connection(db):
    """Accept either a raw DB-API connection or a store, and return the
    underlying connection.
    """
    return getattr(db, "connection", db)


class MailboxStore:
    def __init__(self, db):
        self.connection = _connection(db)

    def __bool__(self):
        return bool(self.connection)

    # -- transactions -----------------------------------------------------

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    # -- version ----------------------------------------------------------

    def get_version(self):
        return self.connection.execute(
            "SELECT version FROM version").fetchone()["version"]

    # -- nameplates -------------------------------------------------------

    def get_nameplate(self, app_id, name):
        return self.connection.execute(
            "SELECT * FROM `nameplates`"
            " WHERE `app_id`=? AND `name`=?",
            (app_id, name)).fetchone()

    def get_nameplate_names(self, app_id):
        rows = self.connection.execute(
            "SELECT DISTINCT `name` FROM `nameplates`"
            " WHERE `app_id`=?", (app_id,)).fetchall()
        return {row["name"] for row in rows}

    def get_nameplates(self, app_id):
        return self.connection.execute(
            "SELECT * FROM `nameplates`"
            " WHERE `app_id`=?", (app_id,)).fetchall()

    def insert_nameplate(self, app_id, name, mailbox_id):
        return self.connection.execute(
            "INSERT INTO `nameplates`"
            " (`app_id`, `name`, `mailbox_id`)"
            " VALUES(?,?,?)",
            (app_id, name, mailbox_id)).lastrowid

    def delete_nameplate(self, nameplate_id):
        self.connection.execute(
            "DELETE FROM `nameplates` WHERE `id`=?", (nameplate_id,))

    def delete_nameplates_for_mailbox(self, mailbox_id):
        self.connection.execute(
            "DELETE FROM `nameplates` WHERE `mailbox_id`=?", (mailbox_id,))

    def get_nameplate_side(self, nameplate_id, side):
        return self.connection.execute(
            "SELECT * FROM `nameplate_sides`"
            " WHERE `nameplates_id`=? AND `side`=?",
            (nameplate_id, side)).fetchone()

    def get_nameplate_sides(self, nameplate_id):
        return self.connection.execute(
            "SELECT * FROM `nameplate_sides`"
            " WHERE `nameplates_id`=?", (nameplate_id,)).fetchall()

    def insert_nameplate_side(self, nameplate_id, claimed, side, added):
        self.connection.execute(
            "INSERT INTO `nameplate_sides`"
            " (`nameplates_id`, `claimed`, `side`, `added`)"
            " VALUES(?,?,?,?)",
            (nameplate_id, claimed, side, added))

    def set_nameplate_side_claimed(self, nameplate_id, side, claimed):
        self.connection.execute(
            "UPDATE `nameplate_sides` SET `claimed`=?"
            " WHERE `nameplates_id`=? AND `side`=?",
            (claimed, nameplate_id, side))

    def delete_nameplate_sides(self, nameplate_id):
        self.connection.execute(
            "DELETE FROM `nameplate_sides` WHERE `nameplates_id`=?",
            (nameplate_id,))

    def delete_nameplate_sides_for_side(self, side):
        self.connection.execute(
            "DELETE FROM `nameplate_sides` WHERE `side`=?", (side,))

    # -- mailboxes --------------------------------------------------------

    def get_mailbox(self, app_id, mailbox_id):
        return self.connection.execute(
            "SELECT * FROM `mailboxes`"
            " WHERE `app_id`=? AND `id`=?",
            (app_id, mailbox_id)).fetchone()

    def get_mailbox_by_id(self, mailbox_id):
        return self.connection.execute(
            "SELECT * FROM `mailboxes` WHERE `id`=?", (mailbox_id,)).fetchone()

    def get_mailboxes(self, app_id):
        return self.connection.execute(
            "SELECT * FROM `mailboxes` WHERE `app_id`=?", (app_id,)).fetchall()

    def insert_mailbox(self, app_id, mailbox_id, for_nameplate, updated):
        self.connection.execute(
            "INSERT INTO `mailboxes`"
            " (`app_id`, `id`, `for_nameplate`, `updated`)"
            " VALUES(?,?,?,?)",
            (app_id, mailbox_id, for_nameplate, updated))

    def update_mailbox_updated(self, mailbox_id, updated):
        self.connection.execute(
            "UPDATE `mailboxes` SET `updated`=? WHERE `id`=?",
            (updated, mailbox_id))

    def delete_mailbox(self, mailbox_id):
        self.connection.execute(
            "DELETE FROM `mailboxes` WHERE `id`=?", (mailbox_id,))

    # -- mailbox sides ----------------------------------------------------

    def get_mailbox_side(self, mailbox_id, side):
        return self.connection.execute(
            "SELECT * FROM `mailbox_sides`"
            " WHERE `mailbox_id`=? AND `side`=?",
            (mailbox_id, side)).fetchone()

    def get_mailbox_sides(self, mailbox_id):
        return self.connection.execute(
            "SELECT * FROM `mailbox_sides`"
            " WHERE `mailbox_id`=?", (mailbox_id,)).fetchall()

    def insert_mailbox_side(self, mailbox_id, opened, side, added):
        self.connection.execute(
            "INSERT INTO `mailbox_sides`"
            " (`mailbox_id`, `opened`, `side`, `added`)"
            " VALUES(?,?,?,?)",
            (mailbox_id, opened, side, added))

    def close_mailbox_side(self, mailbox_id, side, mood):
        self.connection.execute(
            "UPDATE `mailbox_sides` SET `opened`=?, `mood`=?"
            " WHERE `mailbox_id`=? AND `side`=?",
            (False, mood, mailbox_id, side))

    def delete_mailbox_sides(self, mailbox_id):
        self.connection.execute(
            "DELETE FROM `mailbox_sides` WHERE `mailbox_id`=?",
            (mailbox_id,))

    # -- messages ---------------------------------------------------------

    def get_messages(self, app_id, mailbox_id):
        return self.connection.execute(
            "SELECT * FROM `messages`"
            " WHERE `app_id`=? AND `mailbox_id`=?"
            " ORDER BY `server_rx` ASC",
            (app_id, mailbox_id)).fetchall()

    def insert_message(self, app_id, mailbox_id, side, phase, body,
                       server_rx, msg_id):
        self.connection.execute(
            "INSERT INTO `messages`"
            " (`app_id`, `mailbox_id`, `side`, `phase`,  `body`,"
            "  `server_rx`, `msg_id`)"
            " VALUES (?,?,?,?,?, ?,?)",
            (app_id, mailbox_id, side, phase, body, server_rx, msg_id))

    def delete_messages(self, mailbox_id):
        self.connection.execute(
            "DELETE FROM `messages` WHERE `mailbox_id`=?", (mailbox_id,))

    # -- app discovery ----------------------------------------------------

    def get_app_ids(self):
        apps = set()
        for table in ("nameplates", "mailboxes", "messages"):
            rows = self.connection.execute(
                "SELECT DISTINCT `app_id` FROM `%s`" % table).fetchall()
            apps.update(row["app_id"] for row in rows)
        return apps

    # -- address-id generations ------------------------------------------

    def get_addrid_generation(self):
        return self.connection.execute(
            "SELECT * FROM `addrid_generation`").fetchone()

    def replace_addrid_generation(self, generation, started):
        self.connection.execute("DELETE FROM `addrid_generation`")
        self.connection.execute(
            "INSERT INTO `addrid_generation`"
            " (`generation`, `started`)"
            " VALUES(?,?)",
            (generation, started))

    # -- connections ------------------------------------------------------

    def clear_connections(self):
        self.connection.execute("DELETE FROM `connection_messages`")
        self.connection.execute("DELETE FROM `connections`")

    def insert_connection(self, addrid_generation, addrid_counter,
                          connected, active):
        return self.connection.execute(
            "INSERT INTO `connections`"
            " (`addrid_generation`, `addrid_counter`, `connected`, `active`)"
            " VALUES(?,?,?,?)",
            (addrid_generation, addrid_counter, connected, active)).lastrowid

    def bind_connection(self, connection_id, side, implementation, version):
        self.connection.execute(
            "UPDATE `connections`"
            " SET `side`=?, `implementation`=?, `version`=?"
            " WHERE `id`=?",
            (side, implementation, version, connection_id))

    def update_connection_active(self, connection_id, active):
        self.connection.execute(
            "UPDATE `connections`"
            " SET `active`=?"
            " WHERE `id`=?",
            (active, connection_id))

    def insert_connection_message(self, connection_id, when, name):
        self.connection.execute(
            "INSERT INTO `connection_messages`"
            " (`id`, `when`, `name`)"
            " VALUES(?,?,?)",
            (connection_id, when, name))

    def delete_connection_messages(self, connection_id):
        self.connection.execute(
            "DELETE FROM `connection_messages` WHERE `id`=?", (connection_id,))

    def delete_connection(self, connection_id):
        self.connection.execute(
            "DELETE FROM `connections` WHERE `id`=?", (connection_id,))


class UsageStore:
    def __init__(self, db):
        self.connection = _connection(db)

    def __bool__(self):
        return bool(self.connection)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def insert_client_version(self, app_id, side, connect_time,
                              implementation, version):
        self.connection.execute(
            "INSERT INTO `client_versions`"
            " (`app_id`, `side`, `connect_time`,"
            "  `implementation`, `version`)"
            " VALUES(?,?,?,?,?)",
            (app_id, side, connect_time, implementation, version))

    def insert_nameplate_usage(self, app_id, started, total_time,
                               waiting_time, result):
        self.connection.execute(
            "INSERT INTO `nameplates`"
            " (`app_id`,"
            " `started`, `total_time`, `waiting_time`, `result`)"
            " VALUES (?, ?,?,?,?)",
            (app_id, started, total_time, waiting_time, result))

    def insert_mailbox_usage(self, app_id, for_nameplate, started, total_time,
                             waiting_time, result):
        self.connection.execute(
            "INSERT INTO `mailboxes`"
            " (`app_id`, `for_nameplate`,"
            "  `started`, `total_time`, `waiting_time`, `result`)"
            " VALUES (?,?, ?,?,?,?)",
            (app_id, for_nameplate, started, total_time, waiting_time, result))

    def replace_current(self, rebooted, updated, blur_time,
                        connections_websocket):
        self.connection.execute("DELETE FROM `current`")
        self.connection.execute(
            "INSERT INTO `current`"
            " (`rebooted`, `updated`, `blur_time`,"
            "  `connections_websocket`)"
            " VALUES(?,?,?,?)",
            (rebooted, updated, blur_time, connections_websocket))


class AddressIDStore:
    def __init__(self, db):
        self.connection = _connection(db)

    def __bool__(self):
        return bool(self.connection)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def clear(self):
        self.connection.execute("DELETE FROM `address_ids`")

    def get_address_id(self, addr_type, addr):
        return self.connection.execute(
            "SELECT * FROM `address_ids`"
            " WHERE `type`=? AND `address`=?",
            (addr_type, addr)).fetchone()

    def get_max_counter(self, generation):
        return self.connection.execute(
            "SELECT `counter` FROM `address_ids`"
            " WHERE `generation`=?"
            " ORDER BY `counter` DESC"
            " LIMIT 1",
            (generation,)).fetchone()

    def insert_address_id(self, generation, counter, addr_type, address):
        self.connection.execute(
            "INSERT INTO `address_ids`"
            " (`generation`, `counter`, `type`, `address`)"
            " VALUES(?,?,?,?)",
            (generation, counter, addr_type, address))

    def get_address(self, generation, counter):
        return self.connection.execute(
            "SELECT * FROM `address_ids`"
            " WHERE `generation`=? AND `counter`=?",
            (generation, counter)).fetchone()
