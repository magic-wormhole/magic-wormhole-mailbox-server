"""Persistence layer for the mailbox server.

The Twisted/WebSocket protocol code must not contain SQL. All database
access goes through the small store classes defined here:

* :class:`MailboxStore` owns the channel database (mailboxes, nameplates,
  messages, address-id generations, and connection bookkeeping).
* :class:`UsageStore` owns the optional usage database (operational
  history).
* :class:`AddressIDStore` owns the optional address-id database.

The stores use SQLAlchemy Core expressions against the tables declared in
:mod:`wormhole_mailbox_server.schema`. Each store holds one SQLAlchemy
:class:`~sqlalchemy.engine.Connection`; callers continue to control commit
boundaries explicitly through :meth:`commit` so the Twisted reactor sees the
same durability behavior as before.

``execute()`` is a lower-level compatibility escape hatch used by tests and
legacy tooling. New protocol code should use the named methods.
"""

from contextlib import contextmanager

from sqlalchemy import (Connection, Engine, delete, insert, select,
                        update)

from . import schema


class _Result:
    """Small DB-API-like wrapper returning dict rows."""

    def __init__(self, result):
        if result.returns_rows:
            self._rows = [dict(row) for row in result.mappings().all()]
        else:
            self._rows = []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _Store:
    def __init__(self, bind):
        if isinstance(bind, _Store):
            self.connection = bind.connection
            self.engine = bind.engine
        elif isinstance(bind, Connection):
            self.connection = bind
            self.engine = bind.engine
        elif isinstance(bind, Engine):
            self.engine = bind
            self.connection = bind.connect()
        else:
            raise TypeError("cannot bind a store to %r" % (bind,))

    def __bool__(self):
        return self.connection is not None

    # -- transaction control ---------------------------------------------

    @contextmanager
    def transaction(self):
        """Run a logical operation in one transaction.

        Nested uses (including across store instances that share a
        connection) join the outermost transaction, so protocol methods can
        each declare their own scope without committing partway through a
        larger operation.
        """
        info = self.connection.info
        depth = info.get("wormhole_tx_depth", 0)
        info["wormhole_tx_depth"] = depth + 1
        try:
            yield self
        except Exception:
            info["wormhole_tx_depth"] = depth
            if depth == 0:
                self.connection.rollback()
            raise
        else:
            info["wormhole_tx_depth"] = depth
            if depth == 0:
                self.connection.commit()

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    # -- compatibility escape hatch --------------------------------------

    def execute(self, sql, params=()):
        """Execute raw SQL against the underlying driver connection.

        This exists for tests and legacy tooling only; protocol code must
        use the named methods below.
        """
        return _Result(self.connection.exec_driver_sql(sql, params))


class MailboxStore(_Store):
    # -- nameplates -------------------------------------------------------

    def get_nameplate(self, app_id, name):
        t = schema.nameplates
        row = self.connection.execute(
            select(t).where(t.c.app_id == app_id, t.c.name == name)
        ).mappings().first()
        return dict(row) if row else None

    def get_nameplate_names(self, app_id):
        t = schema.nameplates
        return set(self.connection.execute(
            select(t.c.name).distinct().where(t.c.app_id == app_id)
        ).scalars().all())

    def get_nameplates(self, app_id):
        t = schema.nameplates
        rows = self.connection.execute(
            select(t).where(t.c.app_id == app_id)).mappings().all()
        return [dict(row) for row in rows]

    def insert_nameplate(self, app_id, name, mailbox_id):
        t = schema.nameplates
        result = self.connection.execute(
            insert(t).values(app_id=app_id, name=name,
                             mailbox_id=mailbox_id))
        return result.inserted_primary_key[0]

    def delete_nameplate(self, nameplate_id):
        t = schema.nameplates
        self.connection.execute(delete(t).where(t.c.id == nameplate_id))

    def delete_nameplates_for_mailbox(self, mailbox_id):
        t = schema.nameplates
        self.connection.execute(
            delete(t).where(t.c.mailbox_id == mailbox_id))

    def get_nameplate_side(self, nameplate_id, side):
        t = schema.nameplate_sides
        row = self.connection.execute(
            select(t).where(t.c.nameplates_id == nameplate_id,
                            t.c.side == side)
        ).mappings().first()
        return dict(row) if row else None

    def get_nameplate_sides(self, nameplate_id):
        t = schema.nameplate_sides
        rows = self.connection.execute(
            select(t).where(t.c.nameplates_id == nameplate_id)
        ).mappings().all()
        return [dict(row) for row in rows]

    def insert_nameplate_side(self, nameplate_id, claimed, side, added):
        t = schema.nameplate_sides
        self.connection.execute(
            insert(t).values(nameplates_id=nameplate_id, claimed=claimed,
                             side=side, added=added))

    def set_nameplate_side_claimed(self, nameplate_id, side, claimed):
        t = schema.nameplate_sides
        self.connection.execute(
            update(t)
            .where(t.c.nameplates_id == nameplate_id, t.c.side == side)
            .values(claimed=claimed))

    def delete_nameplate_sides(self, nameplate_id):
        t = schema.nameplate_sides
        self.connection.execute(
            delete(t).where(t.c.nameplates_id == nameplate_id))

    def delete_nameplate_sides_for_side(self, side):
        t = schema.nameplate_sides
        self.connection.execute(delete(t).where(t.c.side == side))

    # -- mailboxes --------------------------------------------------------

    def get_mailbox(self, app_id, mailbox_id):
        t = schema.mailboxes
        row = self.connection.execute(
            select(t).where(t.c.app_id == app_id, t.c.id == mailbox_id)
        ).mappings().first()
        return dict(row) if row else None

    def get_mailbox_by_id(self, mailbox_id):
        t = schema.mailboxes
        row = self.connection.execute(
            select(t).where(t.c.id == mailbox_id)).mappings().first()
        return dict(row) if row else None

    def get_mailboxes(self, app_id):
        t = schema.mailboxes
        rows = self.connection.execute(
            select(t).where(t.c.app_id == app_id)).mappings().all()
        return [dict(row) for row in rows]

    def insert_mailbox(self, app_id, mailbox_id, for_nameplate, updated):
        t = schema.mailboxes
        self.connection.execute(
            insert(t).values(app_id=app_id, id=mailbox_id,
                             for_nameplate=for_nameplate, updated=updated))

    def update_mailbox_updated(self, mailbox_id, updated):
        t = schema.mailboxes
        self.connection.execute(
            update(t).where(t.c.id == mailbox_id).values(updated=updated))

    def delete_mailbox(self, mailbox_id):
        t = schema.mailboxes
        self.connection.execute(delete(t).where(t.c.id == mailbox_id))

    # -- mailbox sides ----------------------------------------------------

    def get_mailbox_side(self, mailbox_id, side):
        t = schema.mailbox_sides
        row = self.connection.execute(
            select(t).where(t.c.mailbox_id == mailbox_id, t.c.side == side)
        ).mappings().first()
        return dict(row) if row else None

    def get_mailbox_sides(self, mailbox_id):
        t = schema.mailbox_sides
        rows = self.connection.execute(
            select(t).where(t.c.mailbox_id == mailbox_id)
        ).mappings().all()
        return [dict(row) for row in rows]

    def insert_mailbox_side(self, mailbox_id, opened, side, added):
        t = schema.mailbox_sides
        self.connection.execute(
            insert(t).values(mailbox_id=mailbox_id, opened=opened,
                             side=side, added=added))

    def close_mailbox_side(self, mailbox_id, side, mood):
        t = schema.mailbox_sides
        self.connection.execute(
            update(t)
            .where(t.c.mailbox_id == mailbox_id, t.c.side == side)
            .values(opened=False, mood=mood))

    def delete_mailbox_sides(self, mailbox_id):
        t = schema.mailbox_sides
        self.connection.execute(
            delete(t).where(t.c.mailbox_id == mailbox_id))

    # -- messages ---------------------------------------------------------

    def get_messages(self, app_id, mailbox_id):
        t = schema.messages
        rows = self.connection.execute(
            select(t)
            .where(t.c.app_id == app_id, t.c.mailbox_id == mailbox_id)
            .order_by(t.c.server_rx.asc(), t.c.id.asc())
        ).mappings().all()
        return [dict(row) for row in rows]

    def insert_message(self, app_id, mailbox_id, side, phase, body,
                       server_rx, msg_id):
        t = schema.messages
        self.connection.execute(
            insert(t).values(app_id=app_id, mailbox_id=mailbox_id,
                             side=side, phase=phase, body=body,
                             server_rx=server_rx, msg_id=msg_id))

    def delete_messages(self, mailbox_id):
        t = schema.messages
        self.connection.execute(delete(t).where(t.c.mailbox_id == mailbox_id))

    # -- app discovery ----------------------------------------------------

    def get_app_ids(self):
        apps = set()
        for t in (schema.nameplates, schema.mailboxes, schema.messages):
            apps.update(self.connection.execute(
                select(t.c.app_id).distinct()).scalars().all())
        return apps

    # -- address-id generations ------------------------------------------

    def get_addrid_generation(self):
        t = schema.addrid_generation
        row = self.connection.execute(select(t)).mappings().first()
        return dict(row) if row else None

    def replace_addrid_generation(self, generation, started):
        t = schema.addrid_generation
        self.connection.execute(delete(t))
        self.connection.execute(
            insert(t).values(generation=generation, started=started))

    # -- connections ------------------------------------------------------

    def clear_connections(self):
        self.connection.execute(delete(schema.connection_messages))
        self.connection.execute(delete(schema.connections))

    def insert_connection(self, addrid_generation, addrid_counter,
                          connected, active):
        t = schema.connections
        result = self.connection.execute(
            insert(t).values(addrid_generation=addrid_generation,
                             addrid_counter=addrid_counter,
                             connected=connected, active=active))
        return result.inserted_primary_key[0]

    def bind_connection(self, connection_id, side, implementation, version):
        t = schema.connections
        self.connection.execute(
            update(t).where(t.c.id == connection_id)
            .values(side=side, implementation=implementation,
                    version=version))

    def update_connection_active(self, connection_id, active):
        t = schema.connections
        self.connection.execute(
            update(t).where(t.c.id == connection_id).values(active=active))

    def insert_connection_message(self, connection_id, when, name):
        t = schema.connection_messages
        self.connection.execute(
            insert(t).values(id=connection_id, when=when, name=name))

    def delete_connection_messages(self, connection_id):
        t = schema.connection_messages
        self.connection.execute(delete(t).where(t.c.id == connection_id))

    def delete_connection(self, connection_id):
        t = schema.connections
        self.connection.execute(delete(t).where(t.c.id == connection_id))


class UsageStore(_Store):
    def insert_client_version(self, app_id, side, connect_time,
                              implementation, version):
        t = schema.client_versions
        self.connection.execute(
            insert(t).values(app_id=app_id, side=side,
                             connect_time=connect_time,
                             implementation=implementation, version=version))

    def insert_nameplate_usage(self, app_id, started, total_time,
                               waiting_time, result):
        t = schema.usage_nameplates
        self.connection.execute(
            insert(t).values(app_id=app_id, started=started,
                             total_time=total_time,
                             waiting_time=waiting_time, result=result))

    def insert_mailbox_usage(self, app_id, for_nameplate, started, total_time,
                             waiting_time, result):
        t = schema.usage_mailboxes
        self.connection.execute(
            insert(t).values(app_id=app_id, for_nameplate=for_nameplate,
                             started=started, total_time=total_time,
                             waiting_time=waiting_time, result=result))

    def replace_current(self, rebooted, updated, blur_time,
                        connections_websocket):
        t = schema.current
        self.connection.execute(delete(t))
        self.connection.execute(
            insert(t).values(rebooted=rebooted, updated=updated,
                             blur_time=blur_time,
                             connections_websocket=connections_websocket))


class AddressIDStore(_Store):
    def clear(self):
        self.connection.execute(delete(schema.address_ids))

    def get_address_id(self, addr_type, addr):
        t = schema.address_ids
        row = self.connection.execute(
            select(t).where(t.c.type == addr_type, t.c.address == addr)
        ).mappings().first()
        return dict(row) if row else None

    def get_max_counter(self, generation):
        t = schema.address_ids
        row = self.connection.execute(
            select(t.c.counter)
            .where(t.c.generation == generation)
            .order_by(t.c.counter.desc())
            .limit(1)
        ).first()
        return {"counter": row[0]} if row else None

    def insert_address_id(self, generation, counter, addr_type, address):
        t = schema.address_ids
        self.connection.execute(
            insert(t).values(generation=generation, counter=counter,
                             type=addr_type, address=address))

    def get_address(self, generation, counter):
        t = schema.address_ids
        row = self.connection.execute(
            select(t).where(t.c.generation == generation,
                            t.c.counter == counter)
        ).mappings().first()
        return dict(row) if row else None
