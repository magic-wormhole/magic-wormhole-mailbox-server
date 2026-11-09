"""Persistent identity for a single mailbox-server replica.

A replica keeps its identity across restarts in a small file (by default
``replica.id``) containing a UUID. The identity is used to attribute rows in
shared databases to the process that wrote them.

The file is created atomically so two processes racing to initialize a new
state directory cannot end up with different identities.
"""

import os
import time
import uuid


def load_or_create_replica_id(path):
    """Return the replica UUID stored in *path*, creating it if necessary."""
    for _ in range(50):
        try:
            return _read_replica_id(path)
        except FileNotFoundError:
            pass
        try:
            _create_replica_id(path)
        except FileExistsError:
            # Another process won the creation race. Its file might not be
            # fully written yet, so retry the read.
            time.sleep(0.01)
    return _read_replica_id(path)


def _read_replica_id(path):
    with open(path, "r", encoding="utf-8") as f:
        value = f.read().strip()
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise ValueError(
            "%s does not contain a valid UUID: %r" % (path, value))


def _create_replica_id(path):
    value = str(uuid.uuid4())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return value
