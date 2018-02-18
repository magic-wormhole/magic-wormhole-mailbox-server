from twisted.web import server, static
from twisted.web.resource import Resource
from .server_websocket import WebSocketServerFactory
from autobahn.twisted.resource import WebSocketResource

class Root(Resource):
    # child_FOO is a nevow thing, not a twisted.web.resource thing
    def __init__(self):
        Resource.__init__(self)
        self.putChild(b"", static.Data(b"Wormhole Relay\n", "text/plain"))

class PrivacyEnhancedSite(server.Site):
    logRequests = True
    def log(self, request):
        if self.logRequests:
            return server.Site.log(self, request)


def make_web_server(server, log_requests, websocket_protocol_options=()):
    root = Root()
    wsrf = WebSocketServerFactory(None, server)
    wsrf.setProtocolOptions(**dict(websocket_protocol_options))
    root.putChild(b"v1", WebSocketResource(wsrf))

    site = PrivacyEnhancedSite(root)
    site.logRequests = log_requests

    return site

