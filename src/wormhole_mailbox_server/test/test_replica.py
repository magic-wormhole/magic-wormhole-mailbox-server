import os
import stat
import uuid

from twisted.trial import unittest

from ..replica import load_or_create_replica_id


class ReplicaID(unittest.TestCase):
    def test_creates_and_persists(self):
        path = self.mktemp()
        first = load_or_create_replica_id(path)
        uuid.UUID(first)
        self.assertEqual(load_or_create_replica_id(path), first)

    def test_reads_existing_value(self):
        path = self.mktemp()
        value = str(uuid.uuid4())
        with open(path, "w", encoding="utf-8") as f:
            f.write(value + "\n")
        self.assertEqual(load_or_create_replica_id(path), value)

    def test_new_file_is_private(self):
        path = self.mktemp()
        load_or_create_replica_id(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_rejects_corrupt_file(self):
        path = self.mktemp()
        with open(path, "w", encoding="utf-8") as f:
            f.write("not-a-uuid\n")
        with self.assertRaises(ValueError):
            load_or_create_replica_id(path)
