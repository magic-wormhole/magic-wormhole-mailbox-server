from twisted.trial import unittest
from ..database import create_channel_db
from ..connections import ConnectionTable

def get_messages(db, id):
    #print(list(db.execute("SELECT * FROM `connection_messages`").fetchall()))
    return [(row["name"], row["when"])
            for row in db.execute("SELECT * FROM `connection_messages`"
                                  " WHERE `id`=?", (id,)).fetchall()
            ]

class ConnectionDB(unittest.TestCase):
    def test_connection_table(self):
        db = create_channel_db(":memory:")
        c = ConnectionTable(db, "replica-1")

        c.clear()
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(rows, [])
        rows = list(db.execute("SELECT * FROM connection_messages").fetchall())
        self.assertEqual(rows, [])

        now = 1
        aid1 = (1,3)
        c1 = c.established(aid1, now)
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(len(rows), 1)
        id1 = rows[0]["id"]
        expected = {
            "id": id1,
            "replica_id": "replica-1",
            "addrid_generation": aid1[0],
            "addrid_counter": aid1[1],
            "connected": now,
            "side": None,
            "implementation": None,
            "version": None,
            "active": now,
            }
        self.assertEqual(rows[0], expected)

        now = 2
        c1.add_message(now, "bind")
        c1.bound("side1", ("impl", "v1"))
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        expected["side"] = "side1"
        expected["implementation"] = "impl"
        expected["version"] = "v1"
        expected["active"] = now
        self.assertEqual(rows[0], expected)

        expected_msgs = [("bind", now)]
        self.assertEqual(get_messages(db, id1), expected_msgs)

        now = 5
        c1.add_message(now, "allocate")
        expected["active"] = now
        expected_msgs.append(("allocate", now))
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(rows[0], expected)
        self.assertEqual(get_messages(db, id1), expected_msgs)

        now = 10
        c1.add_message(now, "open")
        expected["active"] = now
        expected_msgs.append(("open", now))
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(rows[0], expected)
        self.assertEqual(get_messages(db, id1), expected_msgs)

        now = 20
        c1.add_message(now, "close")
        expected["active"] = now
        expected_msgs.append(("close", now))
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(rows[0], expected)
        self.assertEqual(get_messages(db, id1), expected_msgs)

        now = 30
        c1.lost()
        expected_msgs = []
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(rows, [])
        self.assertEqual(get_messages(db, id1), expected_msgs)

    def test_clear(self):
        db = create_channel_db(":memory:")
        c = ConnectionTable(db, "replica-1")

        c.clear()
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(rows, [])
        rows = list(db.execute("SELECT * FROM connection_messages").fetchall())
        self.assertEqual(rows, [])

        now = 1
        aid1 = (1,3)
        c1 = c.established(aid1, now)
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(len(rows), 1)
        id1 = rows[0]["id"]
        c1.add_message(2, "bind")
        c1.add_message(3, "open")
        c1.add_message(4, "add")
        c1.add_message(5, "close")
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(get_messages(db, id1)), 4)

        c.clear()
        rows = list(db.execute("SELECT * FROM connections").fetchall())
        self.assertEqual(len(rows), 0)
        self.assertEqual(len(get_messages(db, id1)), 0)






class ReplicaOwnership(unittest.TestCase):
    def setUp(self):
        self.db = create_channel_db(":memory:")
        self.a = ConnectionTable(self.db, "replica-a")
        self.b = ConnectionTable(self.db, "replica-b")
        with self.db.transaction():
            self.db.register_replica("replica-a", "host-a", 1, 100)
            self.db.register_replica("replica-b", "host-b", 2, 100)

    def _connections(self):
        return self.db.execute("SELECT * FROM connections ORDER BY id").fetchall()

    def _messages(self):
        return self.db.execute("SELECT * FROM connection_messages"
                               " ORDER BY id, `when`").fetchall()

    def _replicas(self):
        return self.db.execute("SELECT * FROM replicas ORDER BY id").fetchall()

    def test_clear_only_touches_own_replica(self):
        ca = self.a.established((1, 1), 100)
        ca.add_message(101, "bind")
        cb = self.b.established((2, 2), 100)
        cb.add_message(101, "bind")

        self.a.clear()

        self.assertEqual([row["replica_id"] for row in self._connections()],
                         ["replica-b"])
        self.assertEqual([row["id"] for row in self._messages()], [cb._id])

    def test_register_clears_previous_run_of_same_replica(self):
        ca = self.a.established((1, 1), 100)
        ca.add_message(101, "bind")
        self.b.established((2, 2), 100)

        with self.db.transaction():
            self.db.register_replica("replica-a", "host-a", 3, 200)

        self.assertEqual([row["replica_id"] for row in self._connections()],
                         ["replica-b"])
        self.assertEqual(self._messages(), [])
        self.assertEqual([row["id"] for row in self._replicas()],
                         ["replica-a", "replica-b"])

    def test_expire_stale_replicas_removes_connections_and_messages(self):
        ca = self.a.established((1, 1), 100)
        ca.add_message(101, "bind")
        cb = self.b.established((2, 2), 100)
        cb.add_message(101, "bind")

        with self.db.transaction():
            self.db.heartbeat_replica("replica-a", 200)
        with self.db.transaction():
            stale = self.db.expire_stale_replicas(150)

        self.assertEqual(stale, ["replica-b"])
        self.assertEqual([row["replica_id"] for row in self._connections()],
                         ["replica-a"])
        self.assertEqual([row["id"] for row in self._messages()], [ca._id])
        self.assertEqual([row["id"] for row in self._replicas()],
                         ["replica-a"])

    def test_expire_removes_unowned_legacy_connections(self):
        legacy = ConnectionTable(self.db).established((3, 3), 100)
        legacy.add_message(101, "bind")

        with self.db.transaction():
            self.db.heartbeat_replica("replica-a", 200)
            self.db.heartbeat_replica("replica-b", 200)
            stale = self.db.expire_stale_replicas(150)

        self.assertEqual(stale, [])
        self.assertEqual(self._connections(), [])
        self.assertEqual(self._messages(), [])

    def test_expire_can_exclude_local_replica(self):
        self.a.established((1, 1), 100)
        self.b.established((2, 2), 100)

        with self.db.transaction():
            stale = self.db.expire_stale_replicas(
                150, exclude_replica_id="replica-a")

        self.assertEqual(stale, ["replica-b"])
        self.assertEqual([row["id"] for row in self._replicas()],
                         ["replica-a"])

    def test_live_view_only_shows_fresh_replicas(self):
        ca = self.a.established((1, 1), 100)
        self.b.established((2, 2), 100)

        with self.db.transaction():
            self.db.heartbeat_replica("replica-a", 200)
        live = self.db.get_live_connections(150)

        self.assertEqual([row["id"] for row in live], [ca._id])

    def test_delete_replica_removes_all_owned_rows(self):
        ca = self.a.established((1, 1), 100)
        ca.add_message(101, "bind")
        cb = self.b.established((2, 2), 100)
        cb.add_message(101, "bind")

        with self.db.transaction():
            self.db.delete_replica("replica-a")

        self.assertEqual([row["id"] for row in self._connections()], [cb._id])
        self.assertEqual([row["id"] for row in self._messages()], [cb._id])
        self.assertEqual([row["id"] for row in self._replicas()],
                         ["replica-b"])
