from twisted.trial import unittest
from ..database import create_channel_db, create_addrid_db
from ..address_id import AddressIDTracker

class AddressID(unittest.TestCase):
    def test_generations(self):
        db = create_channel_db(":memory:")
        addr_db = create_addrid_db(":memory:")
        tracker = AddressIDTracker(db, addr_db)
        duration = 100

        now = 1
        tracker.check_generation(now, duration, force=True)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 1)
        self.assertEqual(row["started"], 1)
        rows = addr_db.execute("SELECT * FROM address_ids").fetchall()
        self.assertEqual(rows, [])

        # generation is still going
        now = 10
        tracker.check_generation(now, duration)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 1)
        self.assertEqual(row["started"], 1)

        # generation just finished, new one starts
        now = 102
        tracker.check_generation(now, duration)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 2)
        self.assertEqual(row["started"], 101)

        # don't accumulate lag
        now = 222
        tracker.check_generation(now, duration)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 3)
        self.assertEqual(row["started"], 201)

        # but if we're so late that the new generation would end early, reset and start from now
        now = 500
        tracker.check_generation(now, duration)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 4)
        self.assertEqual(row["started"], 500)

        # check the edge
        now = 600
        tracker.check_generation(now, duration)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 4)
        self.assertEqual(row["started"], 500)

        now = 601
        tracker.check_generation(now, duration)
        row = db.execute("SELECT * FROM addrid_generation").fetchone()
        self.assertEqual(row["generation"], 5)
        self.assertEqual(row["started"], 600)

    def test_address_ids(self):
        db = create_channel_db(":memory:")
        addr_db = create_addrid_db(":memory:")
        tracker = AddressIDTracker(db, addr_db)
        duration = 100

        now = 1
        tracker.check_generation(now, duration, force=True)

        id1 = tracker.get_id("ipv4", "1.2.3.4")
        self.assertEqual(id1, (1,1))
        id1a = tracker.get_id("ipv4", "1.2.3.4")
        self.assertEqual(id1a, id1)
        id2 = tracker.get_id("ipv4", "2.3.4.5")
        self.assertEqual(id2, (1,2))
        id3 = tracker.get_id("ipv6", "2::3")
        self.assertEqual(id3, (1,3))

        self.assertEqual(tracker.get_address((1,1)), ("ipv4", "1.2.3.4"))
        self.assertEqual(tracker.get_address((1,2)), ("ipv4", "2.3.4.5"))
        self.assertEqual(tracker.get_address((1,3)), ("ipv6", "2::3"))

        now = 105
        tracker.check_generation(now, duration)
        self.assertEqual(tracker.get_address((1,1)), None)
        self.assertEqual(tracker.get_address((1,2)), None)
        self.assertEqual(tracker.get_address((1,3)), None)

        idnext1 = tracker.get_id("ipv4", "1.2.3.4")
        self.assertEqual(idnext1, (2,1))
        idnext1a = tracker.get_id("ipv4", "1.2.3.4")
        self.assertEqual(idnext1a, idnext1)
        idnext2 = tracker.get_id("ipv4", "2.3.4.5")
        self.assertEqual(idnext2, (2,2))
        idnext3 = tracker.get_id("ipv6", "2::3")
        self.assertEqual(idnext3, (2,3))
