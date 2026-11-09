"""Internal pub/sub package.

The transport-independent core lives in :mod:`.core`.  Backend transports
(PostgreSQL, Redis, Kafka) are separate modules and are imported lazily by
:func:`load_transport` when a deployment selects them.
"""

from .core import (DEFAULT_TOPIC, LocalPubSub, PubSub, PubSubError,
                   SingletonPubSub, available_transports, load_transport,
                   register_transport)

__all__ = [
    "DEFAULT_TOPIC",
    "LocalPubSub",
    "PubSub",
    "PubSubError",
    "SingletonPubSub",
    "available_transports",
    "load_transport",
    "register_transport",
]
