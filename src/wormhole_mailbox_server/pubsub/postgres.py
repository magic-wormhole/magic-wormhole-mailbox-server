"""PostgreSQL LISTEN/NOTIFY transport for the internal pub/sub layer.

This is the only built-in transport that supports real cross-process
notification.  It deliberately uses the channel database's existing
SQLAlchemy engine:

* the listener holds one dedicated connection from that engine (LISTEN must
  be scoped to a session, so it cannot share the request connection), and
* notifications are published through the store's own connection when one is
  supplied.

Keeping both on the same engine means the pub/sub transport inherits the same
URL, credentials, pooling, and connection options as the channel database.
"""

import hashlib
import json
import select
import threading

from twisted.python import log

from .core import PubSub, PubSubError


def _channel_name(scope):
    # PostgreSQL channel names are identifiers (max 63 bytes) and are
    # case-folded unless quoted; use a short lowercase hash.
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    return "wm_pubsub_" + digest[:48]


class PostgresPubSub(PubSub):
    """Cross-process pub/sub using PostgreSQL LISTEN/NOTIFY."""

    dialect = "postgresql"

    def __init__(self, engine, publish_connection=None, scope="",
                 instance_id=None):
        super().__init__(instance_id=instance_id)
        self.engine = engine
        self.publish_connection = publish_connection
        self.channel = _channel_name(scope)
        self._stop_event = threading.Event()
        self._listener_raw = None
        self._listener_driver = None
        self._listener_thread = None

    def _start_backend(self):
        self._stop_event.clear()
        try:
            self._open_listener()
            self._listener_thread = threading.Thread(
                target=self._listen_loop,
                name="wormhole-pubsub",
                daemon=True,
            )
            self._listener_thread.start()
        except Exception:
            self._close_listener()
            raise
        log.msg("PostgreSQL pub/sub listening on channel %s" % self.channel)

    def _stop_backend(self):
        self._stop_event.set()
        self._close_listener()
        thread = self._listener_thread
        self._listener_thread = None
        if thread is not None:
            thread.join(10.0)

    def _publish_remote(self, topic, payload):
        message = json.dumps(
            {
                "origin": self.instance_id,
                "topic": topic,
                "payload": payload,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(message.encode("utf-8")) > 7900:
            raise PubSubError("pub/sub message exceeds PostgreSQL's payload limit")

        connection = self.publish_connection
        if connection is None:
            connection = self.engine.connect()
            try:
                self._notify(connection, message)
            finally:
                connection.close()
        else:
            self._notify(connection, message)

    def _notify(self, connection, message):
        owns_transaction = not connection.in_transaction()
        connection.exec_driver_sql(
            "SELECT pg_notify(%s, %s)", (self.channel, message))
        if owns_transaction:
            # An outer transaction would otherwise hold the notification
            # until its commit, so only commit when we started the transaction.
            connection.commit()

    # -- listener thread -------------------------------------------------

    def _open_listener(self):
        raw = self.engine.raw_connection()
        try:
            driver = raw.driver_connection
            _set_autocommit(driver)
            cursor = driver.cursor()
            try:
                cursor.execute('LISTEN "%s"' % self.channel)
            finally:
                cursor.close()
        except Exception:
            raw.close()
            raise
        self._listener_raw = raw
        self._listener_driver = driver

    def _close_listener(self):
        raw = self._listener_raw
        self._listener_raw = None
        self._listener_driver = None
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass

    def _listen_loop(self):
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                self._consume_notifications()
                backoff = 1.0
            except Exception as e:
                if self._stop_event.is_set():
                    break
                log.err(e, _why="PostgreSQL pub/sub listener failed")
                self._close_listener()
                if self._stop_event.wait(backoff):
                    break
                try:
                    self._open_listener()
                    backoff = 1.0
                except Exception as e:
                    log.err(e, _why="unable to reconnect PostgreSQL pub/sub listener")
                    backoff = min(backoff * 2, 30.0)

    def _consume_notifications(self):
        driver = self._listener_driver
        if driver is None:
            return
        notifies = getattr(driver, "notifies", None)
        if callable(notifies):
            # psycopg 3: returns a generator that yields until the timeout.
            while not self._stop_event.is_set():
                for notify in driver.notifies(timeout=1.0):
                    if self._stop_event.is_set():
                        return
                    self._dispatch_remote(notify.payload)
            return
        # psycopg2: poll the connection and drain its notification list.
        while not self._stop_event.is_set():
            ready = select.select([driver], [], [], 1.0)[0]
            if not ready:
                continue
            driver.poll()
            while driver.notifies:
                notify = driver.notifies.pop(0)
                if self._stop_event.is_set():
                    return
                self._dispatch_remote(notify.payload)

    def _dispatch_remote(self, message):
        try:
            event = json.loads(message)
        except Exception:
            log.err(_why="invalid PostgreSQL pub/sub payload")
            return
        if not isinstance(event, dict):
            return
        if event.get("origin") == self.instance_id:
            return
        topic = event.get("topic")
        payload = event.get("payload")
        if not isinstance(topic, str) or not isinstance(payload, dict):
            return
        self._dispatch(topic, payload, remote=True)


def _set_autocommit(driver):
    if hasattr(driver, "autocommit"):
        try:
            driver.autocommit = True
            return
        except Exception:
            pass
    # psycopg2's set_isolation_level(0) means autocommit.
    driver.set_isolation_level(0)


def create_pubsub(store, spec, scope):
    """Build the PostgreSQL transport for the channel store's own engine."""
    return PostgresPubSub(store.engine, store.connection, scope)
