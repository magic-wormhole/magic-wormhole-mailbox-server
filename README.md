# Magic Wormhole Mailbox Server
[![Build Status](https://travis-ci.org/warner/magic-wormhole-mailbox-server.svg?branch=master)](https://travis-ci.org/warner/magic-wormhole-mailbox-server)
[![Windows Build Status](https://ci.appveyor.com/api/projects/status/mfnn5rsyfnrq576a/branch/master?svg=true)](https://ci.appveyor.com/project/warner/magic-wormhole-mailbox-server)
[![codecov.io](https://codecov.io/github/warner/magic-wormhole-mailbox-server/coverage.svg?branch=master)](https://codecov.io/github/warner/magic-wormhole-mailbox-server?branch=master)

This repository holds the code for the main server that
[Magic-Wormhole](http://magic-wormhole.io) clients connect to. The server
performs store-and-forward delivery for small key-exchange and control
messages. Bulk data is sent over a direct TCP connection, or through a
[transit-relay](https://github.com/warner/magit-wormhole-transit-relay).

Clients connect with WebSockets, for low-latency delivery in the happy case
where both clients are attached at the same time. Message are stored in to
enable non-simultaneous clients to make forward progress. The server uses a
small SQLite database for persistence (and clients will reconnect
automatically, allowing the server to be rebooted without losing state). An
optional "usage DB" tracks historical activity for status monitoring and
operational maintenance.

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

This library is compatible with python2.7, 3.4, 3.5, and 3.6 .

