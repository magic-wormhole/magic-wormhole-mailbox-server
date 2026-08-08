
class ConnectionTable(object):
    def __init__(self, db):
        self._db = db

    def clear(self):
        self._db.execute("DELETE FROM `connection_messages`")
        self._db.execute("DELETE FROM `connections`")
        self._db.commit()

    def established(self, address_id, now):
        if not address_id:
            address_id = (None, None) # not tracking addresses
        (addrid_generation, addrid_counter) = address_id
        id = None
        if self._db:
            sql = ("INSERT INTO `connections`"
                   " (`addrid_generation`, `addrid_counter`, `connected`, `active`)"
                   " VALUES(?,?,?,?)")
            id = self._db.execute(sql,
                                  (addrid_generation, addrid_counter, now, now)
                                  ).lastrowid
            self._db.commit()
        return Connection(self._db, id)

class Connection(object):
    def __init__(self, connections_db, id):
        self._db = connections_db
        self._id = id

    def bound(self, side, client_version):
        if self._db:
            (implementation, version) = client_version
            self._db.execute("UPDATE `connections`"
                             " SET `side`=?, `implementation`=?, `version`=?"
                             " WHERE `id`=?",
                             (side, implementation, version, self._id))
            self._db.commit()

    def add_message(self, now, name):
        if self._db:
            self._db.execute("UPDATE `connections`"
                             " SET `active`=?"
                             " WHERE `id`=?",
                             (now, self._id))
            self._db.execute("INSERT INTO `connection_messages`"
                             " (`id`, `when`, `name`)"
                             " VALUES(?,?,?)",
                             (self._id, now, name))
            self._db.commit()

    def lost(self):
        if self._db:
            self._db.execute("DELETE FROM `connection_messages` WHERE `id`=?",
                             (self._id,))
            self._db.execute("DELETE FROM `connections` WHERE `id`=?",
                             (self._id,))
            self._db.commit()
