"""Provide interface functions for the core."""
import logging
import sys

from imjoy.core import (
    TokenConfig,
    WorkspaceInfo,
    current_user,
    current_plugin,
    current_workspace,
    all_workspaces,
)
from imjoy.core.auth import generate_presigned_token

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)


class CoreInterface:
    """Represent the interface of the ImJoy core."""

    # pylint: disable=no-self-use

    def __init__(self, imjoy_api=None):
        """Set up instance."""
        self.imjoy_api = imjoy_api

    def register_service(self, service):
        """Register a service."""
        plugin = current_plugin.get()
        service.provider = plugin.name
        service.providerId = plugin.id
        plugin.workspace._services.append(service)

    def get_plugin(self, name):
        """Return a plugin."""
        workspace = current_workspace.get()

        if name in workspace._plugins:
            return workspace._plugins[name].api
        raise Exception("Plugin not found")

    def get_service(self, name):
        """Return a service."""
        plugin = current_plugin.get()
        return next(
            service
            for service in plugin.workspace._services
            if service.get("name") == name
        )

    def log(self, msg):
        """Log a plugin message."""
        plugin = current_plugin.get()
        logger.info("%s: %s", plugin.name, msg)

    def error(self, msg):
        """Log a plugin error message."""
        plugin = current_plugin.get()
        logger.error("%s: %s", plugin.name, msg)

    def generate_token(self, config: TokenConfig):
        """Generate a token."""

        token_config = TokenConfig.parse_obj(config)
        return generate_presigned_token(current_user.get(), token_config)

    def create_workspace(self, config: WorkspaceInfo):
        workspace = WorkspaceInfo.parse_obj(config)
        if workspace.name in all_workspaces:
            raise Exception(f"Workspace {workspace.name} already exists")

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
