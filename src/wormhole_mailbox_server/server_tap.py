import os, json, time
from twisted.internet import reactor
from twisted.python import usage, log
from twisted.application.service import MultiService
from twisted.application.internet import (TimerService,
                                          StreamServerEndpointService)
from twisted.internet import endpoints
from .increase_rlimits import increase_rlimits
from .server import make_server
from .web import make_web_server
from .database import create_or_upgrade_channel_db, create_or_upgrade_usage_db

LONGDESC = """This plugin sets up a 'Mailbox' server for magic-wormhole.
This service forwards short messages between clients, to perform key exchange
and connection setup."""

class Options(usage.Options):
    synopsis = "[--port=] [--log-fd] [--blur-usage=] [--usage-db=]"
    longdesc = LONGDESC

    optParameters = [
        ("port", "p", "tcp:4000:interface=\:\:", "endpoint to listen on"),
        ("blur-usage", None, None, "round logged access times to improve privacy"),
        ("log-fd", None, None, "write JSON usage logs to this file descriptor"),
        ("channel-db", None, "relay.sqlite", "location for the state database"),
        ("usage-db", None, None, "record usage data (SQLite)"),
        ("advertise-version", None, None, "version to recommend to clients"),
        ("signal-error", None, None, "force all clients to fail with a message"),
        ("motd", None, None, "Send a Message of the Day in the welcome"),
        ]
    optFlags = [
        ("disallow-list", None, "refuse to send list of allocated nameplates"),
        ]

    def __init__(self):
        super(Options, self).__init__()
        self["websocket-protocol-options"] = []
        self["allow-list"] = True

    def opt_disallow_list(self):
        self["allow-list"] = False

    def opt_log_fd(self, arg):
        self["log-fd"] = int(arg)

    def opt_blur_usage(self, arg):
        # --blur-usage= is in seconds. If the option isn't provided, we'll keep
        # the default of None
        self["blur-usage"] = int(arg)

    def opt_websocket_protocol_option(self, arg):
        """A websocket server protocol option to configure: OPTION=VALUE. This option can be provided multiple times."""
        try:
            key, value = arg.split("=", 1)
        except ValueError:
            raise usage.UsageError("format options as OPTION=VALUE")
        try:
            value = json.loads(value)
        except:
            raise usage.UsageError("could not parse JSON value for {}".format(key))
        self["websocket-protocol-options"].append((key, value))


SECONDS = 1.0
MINUTE = 60*SECONDS

# CHANNEL_EXPIRATION_TIME should be longer than EXPIRATION_CHECK_PERIOD
CHANNEL_EXPIRATION_TIME = 11*MINUTE
EXPIRATION_CHECK_PERIOD = 5*MINUTE

def makeService(config, channel_db="relay.sqlite", reactor=reactor):
    increase_rlimits()

    parent = MultiService()

    channel_db = create_or_upgrade_channel_db(config["channel-db"])
    usage_db = create_or_upgrade_usage_db(config["usage-db"])
    log_file = (os.fdopen(int(config["log-fd"]), "w")
                if config["log-fd"] is not None
                else None)
    server = make_server(channel_db,
                         allow_list=config["allow-list"],
                         advertise_version=config["advertise-version"],
                         signal_error=config["signal-error"],
                         blur_usage=config["blur-usage"],
                         usage_db=usage_db,
                         log_file=log_file,
                         welcome_motd=config["motd"],
                         )
    server.setServiceParent(parent)
    rebooted = time.time()
    def expire():
        now = time.time()
        old = now - CHANNEL_EXPIRATION_TIME
        try:
            server.prune_all_apps(now, old)
        except Exception as e:
            # catch-and-log exceptions during prune, so a single error won't
            # kill the loop. See #13 for details.
            log.msg("error during prune_all_apps")
            log.err(e)
        server.dump_stats(now, rebooted=rebooted)
    TimerService(EXPIRATION_CHECK_PERIOD, expire).setServiceParent(parent)

    log_requests = config["blur-usage"] is None
    site = make_web_server(server, log_requests,
                           config["websocket-protocol-options"])
    ep = endpoints.serverFromString(reactor, config["port"]) # to listen
    StreamServerEndpointService(ep, site).setServiceParent(parent)
    log.msg("websocket listening on ws://HOSTNAME:PORT/v1")

    return parent
