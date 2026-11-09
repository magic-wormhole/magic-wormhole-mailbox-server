"""Redis transport for the internal pub/sub layer.

Redis is independent of the channel database, so it can provide cross-process
fan-out for SQLite, MySQL, or PostgreSQL deployments.  The ``redis`` package
is an optional dependency; selecting this transport without it installed
raises :class:`~wormhole_mailbox_server.pubsub.PubSubError`.
"""

import hashlib
import json
import threading

from twisted.python import log

from .core import PubSub, PubSubError


def _channel_name(scope):
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    return "wormhole_mailbox:" + digest


class RedisPubSub(PubSub):
    """Cross-process pub/sub using Redis Pub/Sub."""

    dialect = "redis"

    def __init__(self, url, channel, instance_id=None):
        super().__init__(instance_id=instance_id)
        self.url = url
        self.channel = channel
        self._redis = None
        self._client = None
        self._pubsub = None
        self._stop_event = threading.Event()
        self._listener_thread = None

    def _start_backend(self):
        try:
            import redis
        except ImportError:
            raise PubSubError(
                "the Redis pub/sub backend requires the 'redis' package; "
                "install magic-wormhole-mailbox-server[redis]")

        self._redis = redis
        self._client = redis.Redis.from_url(
            self.url, decode_responses=True)
        self._stop_event.clear()
        try:
            self._connect()
            self._listener_thread = threading.Thread(
                target=self._listen_loop,
                name="wormhole-pubsub-redis",
                daemon=True,
            )
            self._listener_thread.start()
        except Exception:
            self._close_client()
            raise
        log.msg("Redis pub/sub listening on %s (%s)"
                % (self.channel, self.url))

    def _stop_backend(self):
        self._stop_event.set()
        self._close_subscription()
        thread = self._listener_thread
        self._listener_thread = None
        if thread is not None:
            thread.join(10.0)
        self._close_client()

    def _connect(self):
        pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(self.channel)
        self._pubsub = pubsub

    def _close_subscription(self):
        pubsub = self._pubsub
        self._pubsub = None
        if pubsub is not None:
            try:
                pubsub.close()
            except Exception:
                pass

    def _close_client(self):
        self._close_subscription()
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

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
        self._client.publish(self.channel, message)

    def _listen_loop(self):
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                pubsub = self._pubsub
                if pubsub is None:
                    self._connect()
                    pubsub = self._pubsub
                for message in pubsub.listen():
                    if self._stop_event.is_set():
                        return
                    if message.get("type") != "message":
                        continue
                    self._dispatch_remote(message.get("data"))
                backoff = 1.0
            except Exception as e:
                if self._stop_event.is_set():
                    break
                log.err(e, _why="Redis pub/sub listener failed")
                self._close_subscription()
                if self._stop_event.wait(backoff):
                    break
                backoff = min(backoff * 2, 30.0)

    def _dispatch_remote(self, message):
        try:
            event = json.loads(message)
        except Exception:
            log.err(_why="invalid Redis pub/sub payload")
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


def create_pubsub(store, spec, scope):
    """Build the Redis transport from an explicit ``redis://`` URL."""
    return RedisPubSub(spec, _channel_name(scope))
