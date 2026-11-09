# Magic Wormhole Mailbox Server
[![PyPI](http://img.shields.io/pypi/v/magic-wormhole-mailbox-server.svg)](https://pypi.python.org/pypi/magic-wormhole-mailbox-server)
![Tests](https://github.com/magic-wormhole/magic-wormhole-transit-relay/workflows/Tests/badge.svg)
[![codecov.io](https://codecov.io/github/magic-wormhole/magic-wormhole-transit-relay/coverage.svg?branch=master)](https://codecov.io/github/magic-wormhole/magic-wormhole-transit-relay?branch=master)

This repository holds the code for the main server that
[Magic-Wormhole](http://magic-wormhole.io) clients connect to. The server
performs store-and-forward delivery for small key-exchange and control
messages. Bulk data is sent over a direct TCP connection, or through a
[transit-relay](https://github.com/magic-wormhole/magic-wormhole-transit-relay).

Clients connect with WebSockets, for low-latency delivery in the happy case
where both clients are attached at the same time. Message are stored to
enable non-simultaneous clients to make forward progress. The server uses a
small SQLite database for persistence (and clients will reconnect
automatically, allowing the server to be rebooted without losing state). An
optional "usage DB" tracks historical activity for status monitoring and
operational maintenance.

## Installation

```
pip install magic-wormhole-mailbox-server
```

You either want to do this into a "user" environment (putting the ``twist``
and ``twistd`` executables in ``~/.local/bin/``) like this:

```
pip install --user magic-wormhole-mailbox-server
```

or put it into a virtualenv, to avoid modifying the system python's
libraries, like this:

```
virtualenv venv
source venv/bin/activate
pip install magic-wormhole-mailbox-server
```

You probably *don't* want to use ``sudo`` when you run ``pip``, since the
dependencies that get installed may conflict with other python programs on
your computer. ``pipsi`` is usually a good way to install into isolated
environments, but unfortunately it doesn't work for
magic-wormhole-mailbox-server, because we don't have a dedicated command to
start the server (``twist``, described below, comes from the ``twisted``
package, and pipsi doesn't expose executables from dependencies).

For the installation from source, ``clone`` this repo, ``cd`` into the folder,
create and activate a virtualenv, and run ``pip install .``.

## Running A Server

Note that the standard [Magic-Wormhole](http://magic-wormhole.io)
command-line tool is preconfigured to use a mailbox server hosted by the
project, so running your own server is only necessary for custom applications
that use magic-wormhole as a library.

The mailbox server is deployed as a twist/twistd plugin. Running a basic
server looks like this:

```
twist wormhole-mailbox --usage-db=usage.sqlite
```

Use ``twist wormhole-mailbox --help`` for more details.

If you use the default ``--port=tcp:4000``, on a machine named
``example.com``, then clients can reach your server with the following
option:

```
wormhole --relay-url=ws://example.com:4000/v1 send FILENAME
```

## Using Docker

The repository includes a multi-stage `misc/Dockerfile` that installs this
package into a slim Python image, runs the server as an unprivileged user,
and keeps all state in `/data`.

Build:

```shell
docker build -f misc/Dockerfile -t magic-wormhole-mailbox .
```

Run (the named volume persists `relay.sqlite` and `usage.sqlite`):

```shell
docker run -d --name wormhole-mailbox \
  -p 4000:4000 \
  -v wormhole-mailbox-data:/data \
  magic-wormhole-mailbox
```

The container entrypoint is `twist wormhole-mailbox`; its default arguments
are:

```
--channel-db=/data/relay.sqlite
--usage-db=/data/usage.sqlite
--port=tcp:4000
```

Override any of them by appending arguments after the image name. For
example, to disable the usage database and add IP-address tracking:

```shell
docker run -d --name wormhole-mailbox \
  -p 4000:4000 \
  -v wormhole-mailbox-data:/data \
  magic-wormhole-mailbox \
  --channel-db=/data/relay.sqlite \
  --addrid-db=/data/addrid.sqlite \
  --port=tcp:4000
```

The image exposes port `4000` and includes a TCP healthcheck. Client
commands point at the mapped port:

```shell
wormhole --relay-url=ws://localhost:4000/v1 send FILENAME
```

## Database backends and migrations

SQLite remains the default: `--channel-db` accepts a filename (or
`:memory:`), and `--usage-db` / `--addrid-db` are optional SQLite files.
The three databases can also be pointed at any SQLAlchemy URL containing
`://` (for example `postgresql://user:pass@host/dbname`).

Schema changes are applied with Alembic at startup. Migration execution is
serialized per database (advisory locks on PostgreSQL/MySQL, a lock file
for SQLite), so multiple server processes can share the same database.
Existing SQLite databases created with older releases are upgraded through
the legacy versioned SQL scripts, backed up first, and then stamped into the
Alembic revision history.

Live WebSocket fan-out is also database-backed. PostgreSQL uses
`LISTEN`/`NOTIFY`, so several server processes can share a channel database
and deliver messages to clients connected to any replica. Redis or Kafka can
be selected as an independent transport for any channel database with
`--pubsub=redis://host:6379/0` or `--pubsub=kafka://host:9092` (install the
`redis` or `kafka` extra). SQLite and MySQL/MariaDB have no equivalent
asynchronous notification primitive; for those backends the server holds a
process-lifetime lock and refuses to start a second process against the same
database unless Redis or Kafka is configured. Use PostgreSQL, Redis, or
Kafka for a horizontally scaled deployment.

To run the unit suites against SQLite, MySQL, and PostgreSQL in parallel,
followed by the five behavioral suites, use
`misc/backends/test-backends.py` (see `misc/backends/README.md`).

## License, Compatibility

This library is released under the MIT license, see LICENSE for details.

This library is compatible with python3 (3.10 and higher).
