"""Kafka transport for the internal pub/sub layer.

Kafka is independent of the channel database, so it can provide cross-process
fan-out for SQLite, MySQL, or PostgreSQL deployments.  The ``confluent-kafka``
package is an optional dependency; selecting this transport without it
installed raises :class:`~wormhole_mailbox_server.pubsub.PubSubError`.

Each server process uses a consumer group of its own, so every process
receives every message (Kafka's normal group behaviour would otherwise
distribute messages between replicas).  Messages are keyed by mailbox so all
events for one mailbox land in the same partition and keep their order.
"""

import hashlib
import json
import threading
import time
from urllib.parse import parse_qs, urlparse

from twisted.python import log

from .core import PubSub, PubSubError


DEFAULT_GROUP = "wormhole-mailbox-pubsub"


def _topic_name(scope):
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    # Kafka topic names are limited to [a-zA-Z0-9._-] and 249 characters.
    return "wormhole_mailbox." + digest


def _parse_spec(spec):
    parsed = urlparse(spec)
    if parsed.scheme != "kafka":
        raise PubSubError("invalid Kafka pub/sub URL %r" % spec)
    servers = parsed.netloc or "127.0.0.1:9092"
    topic = parsed.path.strip("/") or None
    query = parse_qs(parsed.query)
    group = query.get("group", [DEFAULT_GROUP])[0] or DEFAULT_GROUP
    partitions = int(query.get("partitions", ["1"])[0])
    create = query.get("create", ["true"])[0].lower() not in (
        "0", "false", "no")
    return servers, topic, group, partitions, create


class KafkaPubSub(PubSub):
    """Cross-process pub/sub using Kafka topics."""

    dialect = "kafka"

    def __init__(self, servers, topic, group, partitions=1, create=True,
                 instance_id=None):
        super().__init__(instance_id=instance_id)
        self.servers = servers
        self.topic = topic
        self.partitions = partitions
        self.create = create
        # A unique group per process ensures broadcast rather than
        # work-sharing semantics.
        self.group = "%s.%s" % (group, self.instance_id)
        self._producer = None
        self._consumer = None
        self._stop_event = threading.Event()
        self._listener_thread = None

    def _start_backend(self):
        try:
            import confluent_kafka
            from confluent_kafka.admin import AdminClient, NewTopic
        except ImportError:
            raise PubSubError(
                "the Kafka pub/sub backend requires the 'confluent-kafka' "
                "package; install magic-wormhole-mailbox-server[kafka]")

        self._confluent_kafka = confluent_kafka
        self._admin_client_cls = AdminClient
        self._new_topic_cls = NewTopic
        self._stop_event.clear()
        self._producer = confluent_kafka.Producer({
            "bootstrap.servers": self.servers,
            "message.timeout.ms": 10000,
        })
        try:
            self._ensure_topic()
            self._open_consumer()
            self._wait_ready(10.0)
            self._listener_thread = threading.Thread(
                target=self._listen_loop,
                name="wormhole-pubsub-kafka",
                daemon=True,
            )
            self._listener_thread.start()
        except Exception:
            self._close_consumer()
            self._close_producer()
            raise
        log.msg("Kafka pub/sub listening on %s (%s, group %s)"
                % (self.topic, self.servers, self.group))

    def _ensure_topic(self):
        """Create the topic when configured to, so subscription can start.

        Many brokers disable auto-creation, and consumers do not reliably
        trigger it.  Creating the topic up front also means the consumer has
        an assignment before the first message is published.
        """
        if not self.create:
            return
        admin = self._admin_client_cls({
            "bootstrap.servers": self.servers,
        })
        new_topic = self._new_topic_cls(
            self.topic, num_partitions=self.partitions, replication_factor=1)
        futures = admin.create_topics(
            [new_topic], operation_timeout=10, request_timeout=10)
        for future in futures.values():
            try:
                future.result(15)
            except Exception as e:
                error = e.args[0] if e.args else None
                code = getattr(error, "code", None)
                exists = (
                    self._confluent_kafka.KafkaError.TOPIC_ALREADY_EXISTS)
                if callable(code) and code() == exists:
                    continue
                log.msg("unable to create Kafka topic %s: %s"
                        % (self.topic, e))

    def _stop_backend(self):
        self._stop_event.set()
        thread = self._listener_thread
        self._listener_thread = None
        if thread is not None:
            thread.join(10.0)
        self._close_consumer()
        self._close_producer()

    def _open_consumer(self):
        self._consumer = self._confluent_kafka.Consumer({
            "bootstrap.servers": self.servers,
            "group.id": self.group,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
            "allow.auto.create.topics": True,
        })
        self._consumer.subscribe([self.topic])

    def _wait_ready(self, timeout):
        """Wait for group assignment so startup publishes are not missed."""
        consumer = self._consumer
        if consumer is None:
            return
        deadline = time.monotonic() + timeout
        while not self._stop_event.is_set():
            if consumer.assignment():
                return
            if time.monotonic() >= deadline:
                log.msg("Kafka pub/sub consumer has no partition assignment "
                        "for %s yet" % self.topic)
                return
            consumer.poll(0.2)

    def _close_consumer(self):
        consumer = self._consumer
        self._consumer = None
        if consumer is not None:
            try:
                consumer.close()
            except Exception:
                pass

    def _close_producer(self):
        producer = self._producer
        self._producer = None
        if producer is not None:
            try:
                producer.flush(5.0)
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
        # Keep per-mailbox ordering by routing on the mailbox id.
        key = ("%s:%s" % (payload.get("app_id", ""),
                          payload.get("mailbox_id", ""))).encode("utf-8")
        producer = self._producer
        if producer is None:
            raise PubSubError("Kafka pub/sub producer is not running")
        producer.produce(
            self.topic,
            value=message.encode("utf-8"),
            key=key,
            on_delivery=self._delivery_report,
        )
        producer.poll(0)

    @staticmethod
    def _delivery_report(error, message):
        if error is not None:
            log.err(error, _why="unable to publish Kafka pub/sub message")

    def _listen_loop(self):
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                self._consume()
                backoff = 1.0
            except Exception as e:
                if self._stop_event.is_set():
                    break
                log.err(e, _why="Kafka pub/sub listener failed")
                self._close_consumer()
                if self._stop_event.wait(backoff):
                    break
                try:
                    self._open_consumer()
                    backoff = 1.0
                except Exception as e:
                    log.err(e, _why="unable to reconnect Kafka pub/sub "
                                    "listener")
                    backoff = min(backoff * 2, 30.0)

    def _consume(self):
        consumer = self._consumer
        if consumer is None:
            return
        while not self._stop_event.is_set():
            message = consumer.poll(1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                if error.fatal():
                    raise self._confluent_kafka.KafkaException(error)
                log.msg("Kafka pub/sub consumer error: %s" % error)
                continue
            self._dispatch_remote(message.value())

    def _dispatch_remote(self, message):
        if message is None:
            return
        if isinstance(message, bytes):
            message = message.decode("utf-8", "replace")
        try:
            event = json.loads(message)
        except Exception:
            log.err(_why="invalid Kafka pub/sub payload")
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
    """Build the Kafka transport from an explicit ``kafka://`` URL."""
    servers, topic, group, partitions, create = _parse_spec(spec)
    return KafkaPubSub(servers, topic or _topic_name(scope), group,
                       partitions=partitions, create=create)
