"""Provide interface functions for the core."""
import logging
import sys
from contextvars import ContextVar
from typing import Dict

from imjoy.core import WorkspaceInfo, current_user, workspaces
from imjoy.core.auth import generate_presigned_token

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)


class CoreInterface:
    """Represent the interface of the ImJoy core."""

    # pylint: disable=no-self-use

    def __init__(self, plugins=None, imjoy_api=None):
        """Set up instance."""
        self._services = []
        self.imjoy_api = imjoy_api
        self.plugins = plugins

    def register_service(self, plugin, service):
        """Register a service."""
        service.provider = plugin.name
        service.providerId = plugin.id
        self._services.append(service)

    def get_plugin(self, plugin, name):
        """Return a plugin."""
        ws_plugins = self.plugins.get(plugin.workspace.name)
        if ws_plugins and name in ws_plugins:
            return ws_plugins[name].api
        raise Exception("Plugin not found")

    def get_service(self, plugin, name):
        """Return a service."""
        return next(
            service for service in self._services if service.get("name") == name
        )

    def log(self, plugin, msg):
        """Log a plugin message."""
        logger.info("%s: %s", plugin.name, msg)

    def error(self, plugin, msg):
        """Log a plugin error message."""
        logger.error("%s: %s", plugin.name, msg)

    def generate_token(self, plugin, config):
        """Generate a token."""
        return generate_presigned_token(current_user.get(), config)

    def get_interface(self):
        """Return the interface."""
        return {
            "log": self.log,
            "error": self.error,
            "registerService": self.register_service,
            "register_service": self.register_service,
            "getService": self.get_service,
            "get_service": self.get_service,
            "utils": {},
            "getPlugin": self.get_plugin,
            "get_plugin": self.get_plugin,
            "generateToken": self.generate_token,
            "generate_token": self.generate_token,
        }

    def remove_plugin_services(self, plugin):
        """Remove the plugin services."""
        for service in self._services.copy():
            if service.providerId == plugin.id:
                self._services.remove(service)
