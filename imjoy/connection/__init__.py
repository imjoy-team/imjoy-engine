"""Provide the socketio connection manager."""
import asyncio
from functools import partial

import socketio
from aiohttp import web

from imjoy.const import ENG
from imjoy.helper import dotdict
from .decorator import partial_coro
from .handler import register_services
from .server import setup_app, run_app


def create_connection_manager(eng):
    """Create a socketio connection and return the connection instance."""
    # An event handler can be found like this:
    # handler = sio.handlers[namespace][event]
    # ALLOWED_ORIGINS = [opt.base_url, 'http://imjoy.io', 'https://imjoy.io']
    sio = socketio.AsyncServer()
    app = web.Application()
    app[ENG] = eng
    sio.attach(app)
    setup_app(eng, app)
    return ConnectionManager(eng, app, sio)


def register_event_handler(eng, event, handler=None, namespace=None):
    """Register a socketio event handler."""
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


class ConnectionManager:
    """Represent a connection manager for socketio event handler and session data."""

    # pylint: disable=too-few-public-methods

    def __init__(self, eng, app, sio):
        """Set up connection instance attributes."""
        self.eng = eng
        self.app = app
        self.sio = sio
        self.store = dotdict()
        self.reset_store()

    def reset_store(self, reset_clients=True):
        """Reset the connection data store"""
        self.store.attempt_count = 0
        self.store.cmd_history = []
        self.store.plugins = {}
        self.store.plugin_sessions = {}
        self.store.plugin_sids = {}
        self.store.plugin_signatures = {}

        self.store.generatedUrls = {}
        self.store.generatedUrlFiles = {}
        self.store.requestUploadFiles = {}
        self.store.requestUrls = {}
        self.store.terminal_session = {}

        if reset_clients:
            self.store.clients = {}
            self.store.client_sessions = {}
            self.store.registered_sessions = {}

    def start(self):
        """Start the connection."""
        self._register_services()
        run_app(self.eng, self.app)

    def register_event_handler(self, event, handler=None, namespace=None):
        """Register a socketio event handler."""
        register_event_handler(self.eng, event, handler=handler, namespace=namespace)

    def _register_services(self):
        """Register event handlers for internal services."""
        register_services(self.eng, register_event_handler)
