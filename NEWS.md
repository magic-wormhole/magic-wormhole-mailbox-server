
User-visible changes in "magic-wormhole-mailbox-server":

## Upcoming

* (put release-note here when merging / proposing a PR)


## Release 0.5.0 (7-Nov-2024)

* correctly close a mailbox which still has a nameplate (#28)
* remove python2 support
* test on python 3.8, 3.9, 3.10, 3.11 and 3.12 series
* drop "six" (#35)
* upgrade "versioneer"


## Release 0.4.1 (11-Sep-2019)

* listen on IPv4+IPv6 properly (#16)


## Release 0.4.0 (10-Sep-2019)

* listen on IPv4+IPv6 socket by default (#16)
* deallocate AppNamespace objects when empty (#12)
* add client-version-uptake munin plugin
* drop support for py3.3 and py3.4


## Release 0.3.1 (23-Jun-2018)

Record 'None' for when client doesn't supply a version, to make the math
easier.


## Release 0.3.0 (23-Jun-2018)

Fix munin plugins, record client versions in usageDB.


## Release 0.2.0 (16-Jun-2018)

Improve install docs, clean up Munin plugins, add DB migration tool.


## Release 0.1.0 (19-Feb-2018)

Initial release: Forked from magic-wormhole-0.10.5 (14-Feb-2018)
