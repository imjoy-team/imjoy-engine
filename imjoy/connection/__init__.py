"""Provide the socketio connection manager."""
import asyncio
from functools import partial

import socketio

from imjoy.utils import dotdict
from .decorator import partial_coro
from .handler import register_services
from .server import create_app, run_app


def create_connection_manager(engine):
    """Create a socketio connection and return the connection instance."""
    # ALLOWED_ORIGINS = [opt.base_url, 'http://imjoy.io', 'https://imjoy.io']
    sio = socketio.AsyncServer()
    app = create_app(engine)
    sio.attach(app)
    return ConnectionManager(engine, app, sio)


def register_event_handler(engine, event, handler=None, namespace=None):
    """Register a socketio event handler."""
    # An event handler can be found like this:
    # handler = sio.handlers[namespace][event]
    # pylint: disable=protected-access
    if handler is None:
        handler = event
        event = handler._ws_event
        namespace = handler._ws_namespace
    if asyncio.iscoroutinefunction(handler):
        injected_handler = partial_coro(handler, engine)
    else:
        injected_handler = partial(handler, engine)
    engine.conn.sio.on(event, handler=injected_handler, namespace=namespace)


class ConnectionManager:
    """Represent a connection manager for socketio event handler and session data."""

    def __init__(self, engine, app, sio):
        """Set up connection instance attributes."""
        self.engine = engine
        self.app = app
        self.sio = sio
        self.store = dotdict()
        self.reset_store()

    def reset_store(self, reset_clients=True):
        """Reset the connection data store."""
        self.store.attempt_count = 0
        self.store.cmd_history = []
        self.store.plugins = {}
        self.store.plugin_sessions = {}
        self.store.plugin_sids = {}
        self.store.plugin_signatures = {}

        self.store.generated_urls = {}
        self.store.generated_url_files = {}
        self.store.request_upload_files = {}
        self.store.request_urls = {}
        self.store.terminal_session = {}

        if reset_clients:
            self.store.clients = {}
            self.store.client_sessions = {}
            self.store.registered_sessions = {}

    def setup(self):
        """Set up the connection manager."""
        self._register_services()

    def start(self):
        """Start the connection."""
        run_app(self.engine, self.app)

    def register_event_handler(self, event, handler=None, namespace=None):
        """Register a socketio event handler."""
        register_event_handler(self.engine, event, handler=handler, namespace=namespace)

    def _register_services(self):
        """Register event handlers for internal services."""
        register_services(self.engine, register_event_handler)
