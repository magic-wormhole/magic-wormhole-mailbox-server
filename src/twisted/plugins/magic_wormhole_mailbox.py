from twisted.application.service import ServiceMaker

Mailbox = ServiceMaker(
    "Magic-Wormhole Mailbox Server", # name
    "wormhole_mailbox_server.server_tap", # module
    "Provide the Mailbox server for Magic-Wormhole clients.", # desc
    "wormhole-mailbox", # tapname
    )
