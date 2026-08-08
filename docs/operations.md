# Mailbox Server Operations Support

In addition to the nameplates, mailboxes, and messages, which are the core of the Mailbox Server's functionality, the server also tracks information to assist with the operational needs of the service. Overall statistics like connections-per-day and client version distributions help guide development. Some clients are buggy or abusive, and it is helpful to have information on the messages being exchanged to investigate these problems. On the other hand, we want to minimize the amount of information the server is collecting about clients and users.

The goal is to separate, as much as possible, the core functionality of the mailbox server (what clients need), from the data and code that supports operation of the server itself (what the server operators and client developers need). We try to put these different kinds of information into separate database files.

## Side Strings

For each connection, the client submits a `side` string. This is supposed to be a randomly-generated base32 string, long enough to avoid accidental collisions. The `side` is used to track which clients are accessing each nameplate and mailbox. If a client temporarily loses its connection to the mailbox server, it should use the same `side` when it reconnects, otherwise the server will think this is an unrelated client and will signal a "crowded" error.

## Address Identifiers

An "Address Identifier", or "addrid" for short, is a tuple of `(generation, counter)`. Both are positive integers (counting upwards from 1). It is printed as `"addr-%d-%d" % (generation, counter)`.

Within a generation, each unique IP address is assigned the next counter value. The generation is incremented on a periodic basis (about every 24 hours). The `address_ids` table maintains this mapping. Each time the generation is incremented, the `address_ids` table is erased. This table is the only place where IP addresses are recorded. All other logging and operational-support interfaces refer to the addrid instead. This makes it easy to tell when two connections are from the same place, without exposing IP addresses.

This table lives in a separate database. It is enabled by passing `--addrid-db=` when starting the server, pointing at the filename where the DB should be stored. By using `--addrid-db=:memory:`, the database is kept in RAM, reducing the exposure further. The `--generation-duration=` argument specifies (in seconds) the erasure interval, and defaults to 86400 (one day).

## Connection Table

The server maintains a table of active websocket connections. These rows are inserted each time a new connection is established, and deleted when it is lost. The entire table is erased at server startup. This table is kept in the main `--channel-db` database (usually `relay.sqlite`).

The table will show stale information if the server has been stopped (the table is not erased at server shutdown, only startup).

The connection table records:
* addrid (generation,counter)
* connection established time
* last message received time
* side (if any), as established by the BIND message
* (implementation,version) tuple, as reported by the client during BIND

## Usage Database

To measure historical activity, the server maintains another separate "usage" database. If enabled (with `--usage-db=`), this records information about each nameplate and mailbox.

The rows are added as the nameplate/mailbox is retired. This happens when the last side releases their claim on it, either explicitly, or because their connection was lost and the claim timed out (which happens after 10 minutes, by default).

The `nameplates` table records:

* `app_id`
* `started`: timestamp of the nameplate being created
* `waiting_time`: interval from start to the second side appearing
* `total_time`: interval from start to retirement
* `result`: server-side "mood" of the connection: happy/lonely/pruney/crowded

The nameplate `result` indicates what the server thinks about the connection:

* `happy`: two sides used the nameplate and explicitly released it
* `lonely`: only one side ever used the nameplate
* `pruney`: the nameplate was retired because the connections timed out
* `crowded`: three or more sides attempted to use the same nameplate

The `mailboxes` table records:

* `app_id`
* `for_nameplate`: a boolean, True if the mailbox was allocated for a nameplate
* `started`: timestamp of the mailbox being created
* `waiting_time`: interval from start to second side appearing
* `total_time`: interval from start to retirement
* `result`: client-reported "mood": happy/scary/lonely/errory/pruney/crowded

The mailbox `result` indicates what the clients thought about the connection. Each client's CLOSE message includes a "mood", and the server records the most severe mood in the record:

* `happy`: two sides used the mailbox successfully
* `scary`: a client observed cryptographic errors indicative of a failed attack
* `lonely`: only one side ever used the mailbox, or a client never saw their peer's message
* `pruney`: the mailbox was retired because the connections timed out
* `crowded`: three or more sides attempted to open the same mailbox

The usage database also maintains a table of client versions. These are self-reported `(implementation, version)` strings, e.g. `("python", "0.24.0")`. Client developers are encouraged to use a unique string (each `implementation` should have a specific project home page and repository), to facilitate reports of version uptake.

The `client_versions` table gets a new row each time a client connects to the server and issues the BIND command. This does not necessarily mean the client participated in a mailbox connection.

The `side` string is included in the `client_versions` table to help filter out duplicates. The table contains:

* `app_id`
* `side`
* `connect_time`: timestamp of the receipt of the BIND command
* `implementation`, `version`: client-reported version information
