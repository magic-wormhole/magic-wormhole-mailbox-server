from .store import MailboxStore, AddressIDStore


class AddressIDTracker(object):
    def __init__(self, channel_db, addrid_db):
        assert channel_db
        assert addrid_db
        self._channel_store = MailboxStore(channel_db)
        self._addrid_store = AddressIDStore(addrid_db)

    def check_generation(self, now, duration, force=False):
        db = self._channel_store
        row = db.get_addrid_generation()
        if force or not row or (row["started"] + duration) < now:
            next_started = now # first generation starts now
            if row:
                next_started = row["started"] + duration # don't accumulate lag
                if next_started + duration < now:
                    # but don't let the new generation end early
                    next_started = now
            next_generation = row["generation"] + 1 if row else 1
            with db.transaction():
                db.replace_addrid_generation(next_generation, next_started)
            with self._addrid_store.transaction():
                self._addrid_store.clear()

    def get_id(self, addr_type, addr): # -> (generation, counter)
        # we should only record one generation at a time, so there
        # shouldn't be more than one match
        with self._addrid_store.transaction():
            row = self._addrid_store.get_address_id(addr_type, addr)
            if row:
                return (row["generation"], row["counter"])
            # else allocate and insert

            current = self._channel_store.get_addrid_generation()
            assert current
            generation = current["generation"]
            top_row = self._addrid_store.get_max_counter(generation)
            counter = top_row["counter"]+1 if top_row else 1
            self._addrid_store.insert_address_id(generation, counter,
                                                 addr_type, address=addr)
            address_id = (generation, counter)
            return address_id

    def get_address(self, address_id):
        (generation, counter) = address_id
        row = self._addrid_store.get_address(generation, counter)
        if row:
            return (row["type"], row["address"])
        else:
            return None
