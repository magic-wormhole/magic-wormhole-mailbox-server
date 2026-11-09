"""Backend-independent pub/sub interface.

WebSocket listeners are held in a single process, while durable mailbox
state lives in the channel database.  When one process adds a message, its
local listeners are notified directly; other server processes need a way to
learn about the new message so they can wake their own listeners.

This module defines the transport-agnostic part of that mechanism:
subscriptions, local delivery, and lifecycle hooks.  Database-specific
transports live elsewhere and are selected by the database layer.  Local-only
deployments use :class:`LocalPubSub`; backends without a real notification
primitive are wrapped by :class:`SingletonPubSub`, which only permits one
running server process.

The transport contract is deliberately small:

* :meth:`publish` always delivers to local subscribers synchronously.
* A backend may then send the event to other processes.
* :meth:`start` and :meth:`stop` manage any backend resources or locks.

Backend modules live in this package and are loaded lazily through
:func:`load_transport`, so the core never imports Redis, Kafka, or a database
driver.  Third parties can add a transport with :func:`register_transport`.

This module does not import SQLAlchemy or know which database is in use.
"""

import importlib
import threading
import uuid

from twisted.python import log


DEFAULT_TOPIC = "mailbox-message"

# Transport kind -> module that exposes ``create_pubsub(store, spec, scope)``.
# Modules are imported only when a deployment selects them.
_TRANSPORTS = {
    "postgres": "wormhole_mailbox_server.pubsub.postgres",
    "redis": "wormhole_mailbox_server.pubsub.redis",
    "kafka": "wormhole_mailbox_server.pubsub.kafka",
}
_loaded = {}


class PubSubError(RuntimeError):
    """The pub/sub transport cannot be used for this deployment."""


def register_transport(name, module):
    """Register a lazily imported transport module under *name*.

    *module* is a dotted module path.  The module must define
    ``create_pubsub(store, spec, scope)`` and return a :class:`PubSub`.
    Re-registering a name replaces the previous module.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("transport name must be a non-empty string")
    if not isinstance(module, str) or not module:
        raise ValueError("transport module must be a dotted module path")
    _TRANSPORTS[name] = module
    _loaded.pop(name, None)


def available_transports():
    """Return the registered transport names."""
    return tuple(sorted(_TRANSPORTS))


def load_transport(name):
    """Import and return the transport module registered as *name*."""
    try:
        return _loaded[name]
    except KeyError:
        pass
    try:
        module_name = _TRANSPORTS[name]
    except KeyError:
        raise PubSubError(
            "unknown pub/sub transport %r; available: %s"
            % (name, ", ".join(available_transports())))
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise PubSubError(
            "the %s pub/sub transport requires an optional dependency: %s"
            % (name, e)) from e
    if not callable(getattr(module, "create_pubsub", None)):
        raise PubSubError(
            "pub/sub transport module %s does not define create_pubsub()"
            % module_name)
    _loaded[name] = module
    return module


class PubSub:
    """A small in-process pub/sub router with an optional backend transport."""

    dialect = "unknown"

    def __init__(self, instance_id=None):
        self.instance_id = instance_id or uuid.uuid4().hex
        self._subscriptions = {}
        self._subscription_lock = threading.RLock()
        self._started = False
        self._start_lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    @property
    def started(self):
        return self._started

    def start(self):
        with self._start_lock:
            if self._started:
                return
            self._start_backend()
            self._started = True

    def stop(self):
        with self._start_lock:
            if not self._started:
                return
            try:
                self._stop_backend()
            finally:
                self._started = False

    def _start_backend(self):
        pass

    def _stop_backend(self):
        pass

    # -- subscriptions ---------------------------------------------------

    def subscribe(self, topic, callback):
        """Register *callback(topic, payload)*; returns an unsubscribe token."""
        token = object()
        with self._subscription_lock:
            self._subscriptions.setdefault(topic, {})[token] = callback
        return token

    def unsubscribe(self, token):
        with self._subscription_lock:
            for subscribers in self._subscriptions.values():
                if token in subscribers:
                    del subscribers[token]
                    return

    def _dispatch(self, topic, payload, remote):
        with self._subscription_lock:
            callbacks = list(self._subscriptions.get(topic, {}).values())
        for callback in callbacks:
            if remote:
                # A broken remote delivery must not kill the listener thread.
                try:
                    callback(topic, payload)
                except Exception:
                    log.err()
            else:
                callback(topic, payload)

    # -- publishing ------------------------------------------------------

    def publish(self, topic, payload):
        """Deliver locally, then publish to other processes when possible."""
        self._dispatch(topic, payload, remote=False)
        if not self._started:
            return
        try:
            self._publish_remote(topic, payload)
        except Exception as e:
            # The message itself is already durable and local listeners have
            # been notified.  A transport failure should not fail the request;
            # remote clients can still recover by reconnecting and replaying.
            log.err(e, _why="unable to publish message to other processes")

    def _publish_remote(self, topic, payload):
        pass


class LocalPubSub(PubSub):
    """Local-only pub/sub for single-process deployments."""

    dialect = "local"


class SingletonPubSub(PubSub):
    """Pub/sub for backends that cannot notify across processes.

    The supplied lock is held for the life of the server.  A second process
    fails to acquire it and refuses to start, rather than running a replica
    that would never see messages added by the first one.
    """

    dialect = "singleton"

    def __init__(self, lock, instance_id=None):
        super().__init__(instance_id=instance_id)
        self._lock = lock

    def _start_backend(self):
        self._lock.acquire()

    def _stop_backend(self):
        self._lock.release()
