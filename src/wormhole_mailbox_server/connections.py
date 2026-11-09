from .store import MailboxStore


class ConnectionTable(object):
    def __init__(self, db, replica_id=None):
        self._store = MailboxStore(db) if db is not None else None
        self._replica_id = replica_id

    def clear(self):
        if self._store:
            with self._store.transaction():
                self._store.clear_connections(self._replica_id)

    def established(self, address_id, now):
        if not address_id:
            address_id = (None, None) # not tracking addresses
        (addrid_generation, addrid_counter) = address_id
        id = None
        if self._store:
            with self._store.transaction():
                id = self._store.insert_connection(
                    addrid_generation, addrid_counter, now, now,
                    replica_id=self._replica_id)
        return Connection(self._store, id)


class Connection(object):
    def __init__(self, connections_store, id):
        self._store = connections_store
        self._id = id

    def bound(self, side, client_version):
        if self._store:
            (implementation, version) = client_version
            with self._store.transaction():
                self._store.bind_connection(self._id, side, implementation,
                                            version)

    def add_message(self, now, name):
        if self._store:
            with self._store.transaction():
                self._store.update_connection_active(self._id, now)
                self._store.insert_connection_message(self._id, now, name)

    def lost(self):
        if self._store:
            with self._store.transaction():
                self._store.delete_connection_messages(self._id)
                self._store.delete_connection(self._id)
