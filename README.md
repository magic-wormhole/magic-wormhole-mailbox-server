# Magic Wormhole Mailbox Server
[![PyPI](http://img.shields.io/pypi/v/magic-wormhole-mailbox-server.svg)](https://pypi.python.org/pypi/magic-wormhole-mailbox-server)
[![Build Status](https://travis-ci.org/warner/magic-wormhole-mailbox-server.svg?branch=master)](https://travis-ci.org/warner/magic-wormhole-mailbox-server)
[![Windows Build Status](https://ci.appveyor.com/api/projects/status/mfnn5rsyfnrq576a/branch/master?svg=true)](https://ci.appveyor.com/project/warner/magic-wormhole-mailbox-server)
[![codecov.io](https://codecov.io/github/warner/magic-wormhole-mailbox-server/coverage.svg?branch=master)](https://codecov.io/github/warner/magic-wormhole-mailbox-server?branch=master)

This repository holds the code for the main server that
[Magic-Wormhole](http://magic-wormhole.io) clients connect to. The server
performs store-and-forward delivery for small key-exchange and control
messages. Bulk data is sent over a direct TCP connection, or through a
[transit-relay](https://github.com/warner/magic-wormhole-transit-relay).

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

## License, Compatibility

This library is released under the MIT license, see LICENSE for details.

This library is compatible with python2.7, 3.4 (non-Windows-only), 3.5, and
3.6 .
