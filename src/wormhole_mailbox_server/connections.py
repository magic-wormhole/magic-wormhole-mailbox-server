from .store import MailboxStore


class ConnectionTable(object):
    def __init__(self, db):
        self._store = MailboxStore(db) if db is not None else None

    def clear(self):
        self._store.clear_connections()
        self._store.commit()

    def established(self, address_id, now):
        if not address_id:
            address_id = (None, None) # not tracking addresses
        (addrid_generation, addrid_counter) = address_id
        id = None
        if self._store:
            id = self._store.insert_connection(
                addrid_generation, addrid_counter, now, now)
            self._store.commit()
        return Connection(self._store, id)


class Connection(object):
    def __init__(self, connections_store, id):
        self._store = connections_store
        self._id = id

    def bound(self, side, client_version):
        if self._store:
            (implementation, version) = client_version
            self._store.bind_connection(self._id, side, implementation,
                                        version)
            self._store.commit()

    def add_message(self, now, name):
        if self._store:
            self._store.update_connection_active(self._id, now)
            self._store.insert_connection_message(self._id, now, name)
            self._store.commit()

    def lost(self):
        if self._store:
            self._store.delete_connection_messages(self._id)
            self._store.delete_connection(self._id)
            self._store.commit()
