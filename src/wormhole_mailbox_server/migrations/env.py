"""Alembic environment used by the server's startup migration runner.

The application configures three independent databases, each with its own
version table. The engine connection and version-table name are supplied
through ``Config.attributes`` by ``wormhole_mailbox_server.database``.
"""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("migration runner did not supply a connection")

context.configure(
    connection=connection,
    target_metadata=None,
    version_table=context.config.attributes["version_table"],
    render_as_batch=True,
)

with context.begin_transaction():
    context.run_migrations()
