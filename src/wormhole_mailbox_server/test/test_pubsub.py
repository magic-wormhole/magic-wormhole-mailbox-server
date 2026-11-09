import importlib
from unittest import mock

from twisted.trial import unittest

from ..database import create_channel_db, make_pubsub
from ..pubsub import (LocalPubSub, PubSubError, available_transports,
                      load_transport, register_transport)


class LocalDelivery(unittest.TestCase):
    def test_publish_and_unsubscribe(self):
        bus = LocalPubSub()
        received = []
        token = bus.subscribe("topic", lambda topic, payload:
                              received.append((topic, payload)))
        bus.start()
        bus.publish("topic", {"value": 1})
        bus.publish("other", {"value": 2})
        bus.unsubscribe(token)
        bus.publish("topic", {"value": 3})
        bus.stop()
        self.assertEqual(received, [("topic", {"value": 1})])

    def test_remote_errors_do_not_escape(self):
        bus = LocalPubSub()
        received = []

        def broken(topic, payload):
            raise RuntimeError("boom")

        bus.subscribe("topic", broken)
        bus.subscribe("topic", lambda topic, payload:
                      received.append(payload))
        with mock.patch(
                "wormhole_mailbox_server.pubsub.core.log.err") as log_err:
            bus._dispatch("topic", {"value": 1}, remote=True)
        self.assertEqual(log_err.mock_calls, [mock.call()])
        self.assertEqual(received, [{"value": 1}])


class Selection(unittest.TestCase):
    def setUp(self):
        self.store = create_channel_db(":memory:")

    def test_local(self):
        bus = make_pubsub(self.store, "local")
        self.assertIsInstance(bus, LocalPubSub)

    def test_default_sqlite_memory_is_local(self):
        if self.store.engine.dialect.name != "sqlite":
            raise unittest.SkipTest(
                "the unit harness maps :memory: to a real backend")
        self.assertIsInstance(make_pubsub(self.store), LocalPubSub)

    def test_redis_url_is_lazy(self):
        bus = make_pubsub(self.store, "redis://127.0.0.1:6379/0")
        self.assertEqual(bus.dialect, "redis")
        self.assertEqual(bus.url, "redis://127.0.0.1:6379/0")

    def test_kafka_url_is_lazy(self):
        bus = make_pubsub(self.store, "kafka://127.0.0.1:9092")
        self.assertEqual(bus.dialect, "kafka")
        self.assertEqual(bus.servers, "127.0.0.1:9092")
        self.assertTrue(bus.topic.startswith("wormhole_mailbox."))

    def test_kafka_topic_override(self):
        bus = make_pubsub(
            self.store,
            "kafka://127.0.0.1:9092/custom?group=g&partitions=4&create=false")
        self.assertEqual(bus.topic, "custom")
        self.assertTrue(bus.group.startswith("g."))
        self.assertEqual(bus.partitions, 4)
        self.assertFalse(bus.create)

    def test_postgres_selection(self):
        if self.store.engine.dialect.name == "postgresql":
            self.assertEqual(make_pubsub(self.store, "postgres").dialect,
                             "postgresql")
        else:
            self.assertRaises(PubSubError, make_pubsub, self.store,
                              "postgres")

    def test_unknown_backend(self):
        self.assertRaises(PubSubError, make_pubsub, self.store, "nope")


class Registry(unittest.TestCase):
    def test_unknown_transport(self):
        self.assertRaises(PubSubError, load_transport, "does-not-exist")

    def test_builtin_transports_are_registered(self):
        self.assertEqual(
            set(available_transports()) >= {"postgres", "redis", "kafka"},
            True)

    def test_invalid_registration(self):
        self.assertRaises(ValueError, register_transport, "", __name__)
        self.assertRaises(ValueError, register_transport, "x", "")

    def test_registered_transport(self):
        # The test module itself exposes create_pubsub, so it can stand in
        # for a third-party transport module.
        register_transport("test-transport", __name__)
        self.assertIs(load_transport("test-transport"),
                      importlib.import_module(__name__))


def create_pubsub(store, spec, scope):
    """Stand-in factory used by the registry test."""
    return LocalPubSub()
