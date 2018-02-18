#from __future__ import unicode_literals
from twisted.internet import reactor, endpoints
from twisted.internet.defer import inlineCallbacks
from ..database import create_or_upgrade_channel_db, create_or_upgrade_usage_db
from ..server import make_server
from ..web import make_web_server

class ServerBase:
    log_requests = False

    @inlineCallbacks
    def setUp(self):
        self._lp = None
        if self.log_requests:
            blur_usage = None
        else:
            blur_usage = 60.0
        usage_db = create_or_upgrade_usage_db(":memory:")
        yield self._setup_relay(blur_usage=blur_usage, usage_db=usage_db)

    @inlineCallbacks
    def _setup_relay(self, do_listen=False, web_log_requests=False, **kwargs):
        channel_db = create_or_upgrade_channel_db(":memory:")
        self._server = make_server(channel_db, **kwargs)
        if do_listen:
            ep = endpoints.TCP4ServerEndpoint(reactor, 0, interface="127.0.0.1")
            self._site = make_web_server(self._server,
                                         log_requests=web_log_requests)
            self._lp = yield ep.listen(self._site)
            addr = self._lp.getHost()
            self.relayurl = "ws://127.0.0.1:%d/v1" % addr.port
            self.rdv_ws_port = addr.port

    def tearDown(self):
        if self._lp:
            return self._lp.stopListening()
