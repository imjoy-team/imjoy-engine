"""Provide the websocket connection manager."""
import asyncio
from functools import partial

import socketio
from aiohttp import web

from imjoy.const import ENG
from .decorator import partial_coro
from .handler import register_handlers
from .server import setup_app, run_app


def create_connection(eng):
    """Create a websocket connection and return the connection instance."""
    # An event handler can be found like this:
    # handler = sio.handlers[namespace][event]
    # ALLOWED_ORIGINS = [opt.base_url, 'http://imjoy.io', 'https://imjoy.io']
    sio = socketio.AsyncServer()
    app = web.Application()
    app[ENG] = eng
    sio.attach(app)
    setup_app(eng, app)
    return WSConnection(eng, app, sio)


def register_event(eng, event, handler=None, namespace=None):
    """Register a websocket event handler."""
    # pylint: disable=protected-access
    if handler is None:
        handler = event
        event = handler._ws_event
        namespace = handler._ws_namespace
    if asyncio.iscoroutinefunction(handler):
        injected_handler = partial_coro(handler, eng)
    else:
        injected_handler = partial(handler, eng)
    eng.conn.sio.on(event, handler=injected_handler, namespace=namespace)


class WSConnection:
    """Represent a websocket connection."""

    # pylint: disable=too-few-public-methods

    def __init__(self, eng, app, sio):
        """Set up connection instance attributes."""
        self.eng = eng
        self.app = app
        self.sio = sio
        self.data = ConnectionData()

    def start(self):
        """Start the connection."""
        self._register_handlers()
        run_app(self.eng, self.app)

    def register_event(self, event, handler=None, namespace=None):
        """Register a websocket event handler."""
        register_event(self.eng, event, handler=handler, namespace=namespace)

    def _register_handlers(self):
        """Register static websocket event handlers."""
        register_handlers(self.eng, register_event)


class ConnectionData:
    """Represent connection data."""

    # pylint: disable=too-few-public-methods, too-many-instance-attributes

    def __init__(self):
        """Set up the instance."""
        self.attempt_count = 0
        self.cmd_history = []
        self.plugins = {}
        self.plugin_sessions = {}
        self.plugin_sids = {}
        self.plugin_signatures = {}
        self.clients = {}
        self.client_sessions = {}
        self.registered_sessions = {}
        self.generatedUrls = {}
        self.generatedUrlFiles = {}
        self.requestUploadFiles = {}
        self.requestUrls = {}
        self.terminal_session = {}
