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
        c = ConnectionTable(db)

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
        c = ConnectionTable(db)

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




