
class AddressIDTracker(object):
    def __init__(self, channel_db, addrid_db):
        assert channel_db
        assert addrid_db
        self._channel_db = channel_db
        self._addrid_db = addrid_db

    def check_generation(self, now, duration, force=False):
        db = self._channel_db
        row = db.execute("SELECT * FROM `addrid_generation`").fetchone()
        if force or not row or (row["started"] + duration) < now:
            next_started = now # first generation starts now
            if row:
                next_started = row["started"] + duration # don't accumulate lag
                if next_started + duration < now:
                    # but don't let the new generation end early
                    next_started = now
            next_generation = row["generation"] + 1 if row else 1
            db.execute("DELETE FROM `addrid_generation`")
            db.execute("INSERT INTO `addrid_generation`"
                             " (`generation`, `started`)"
                             " VALUES(?,?)",
                             (next_generation, next_started))
            db.commit()
            self._addrid_db.execute("DELETE FROM `address_ids`")
            self._addrid_db.commit()

    def get_id(self, addr_type, addr): # -> (generation, counter)
        # we should only record one generation at a time, so there
        # shouldn't be more than one match
        row = self._addrid_db.execute("SELECT * FROM `address_ids`"
                                      " WHERE `type`=? AND `address`=?",
                                      (addr_type, addr)).fetchone()
        if row:
            return (row["generation"], row["counter"])
        # else allocate and insert

        current = self._channel_db.execute("SELECT * FROM `addrid_generation`").fetchone()
        assert current
        generation = current["generation"]
        top_row = self._addrid_db.execute("SELECT `counter` FROM `address_ids`"
                                          " WHERE `generation`=?"
                                          " ORDER BY `counter` DESC"
                                          " LIMIT 1",
                                          (generation,)).fetchone()
        counter = top_row["counter"]+1 if top_row else 1
        self._addrid_db.execute("INSERT INTO `address_ids`"
                                " (`generation`, `counter`, `type`, `address`)"
                                " VALUES(?,?,?,?)",
                                (generation, counter, addr_type, addr))
        self._addrid_db.commit()
        address_id = (generation, counter)
        return address_id

    def get_address(self, address_id):
        (generation, counter) = address_id
        row = self._addrid_db.execute("SELECT * FROM `address_ids`"
                                      " WHERE `generation`=? AND `counter`=?",
                                      (generation, counter)).fetchone()
        if row:
            return (row["type"], row["address"])
        else:
            return None
