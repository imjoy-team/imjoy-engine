"""Provide the ImJoy core API interface."""
import asyncio
import logging
import sys
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import (  # pylint: disable=no-name-in-module
    BaseModel,
    EmailStr,
    Extra,
    PrivateAttr,
)

from imjoy.core.plugin import DynamicPlugin

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("core")
logger.setLevel(logging.INFO)


class EventBus:
    """An event bus class."""

    def __init__(self):
        """Initialize the event bus."""
        self._callbacks = {}

    def on(self, event_name, func):
        """Register an event callback."""
        self._callbacks[event_name] = self._callbacks.get(event_name, []) + [func]
        return func

    def once(self, event_name, func):
        """Register an event callback that only run once."""
        self._callbacks[event_name] = self._callbacks.get(event_name, []) + [func]
        # mark once callback
        self._callbacks[event_name]._once = True
        return func

    def emit(self, event_name, *data):
        """Trigger an event."""
        for func in self._callbacks.get(event_name, []):
            func(*data)
            if hasattr(func, "_once"):
                self.off(event_name, func)

    def off(self, event_name, func=None):
        """Remove an event callback."""
        if not func:
            del self._callbacks[event_name]
        else:
            self._callbacks.get(event_name, []).remove(func)


class TokenConfig(BaseModel):
    """Represent a token configuration."""

    scopes: List[str]
    expires_in: Optional[int]
    email: Optional[EmailStr]


class VisibilityEnum(str, Enum):
    """Represent the visibility of the workspace."""

    public = "public"
    protected = "protected"


class StatusEnum(str, Enum):
    """Represent the status of a component."""

    ready = "ready"
    initializing = "initializing"
    not_initialized = "not_initialized"


class ServiceConfig(BaseModel):
    """Represent service config."""

    visibility: VisibilityEnum = VisibilityEnum.protected
    require_context: bool = False
    workspace: str
    id: str


class ServiceInfo(BaseModel):
    """Represent service."""

    config: ServiceConfig
    name: str
    type: str

    _provider: DynamicPlugin = PrivateAttr(default_factory=lambda: None)

    class Config:
        """Set the config for pydantic."""

        extra = Extra.allow

    def set_provider(self, provider: DynamicPlugin) -> None:
        """Set the provider plugin."""
        self._provider = provider

    def get_provider(self) -> DynamicPlugin:
        """Get the provider plugin."""
        return self._provider

    def get_summary(self) -> dict:
        """Get a summary about the service."""
        return {
            "name": self.name,
            "type": self.type,
            "provider": self._provider.name,
            "provider_id": self._provider.id,
        }.update(self.config.dict())


class UserInfo(BaseModel):
    """Represent user info."""

    id: str
    roles: List[str]
    is_anonymous: bool
    email: Optional[EmailStr]
    parent: Optional[str]
    scopes: Optional[List[str]]  # a list of workspace
    expires_at: Optional[int]
    _metadata: Dict[str, Any] = PrivateAttr(
        default_factory=lambda: {}
    )  # e.g. s3 credential
    _plugins: Dict[str, DynamicPlugin] = PrivateAttr(
        default_factory=lambda: {}
    )  # id:plugin

    def get_metadata(self) -> Dict[str, Any]:
        """Return the metadata."""
        return self._metadata

    def get_plugins(self) -> Dict[str, DynamicPlugin]:
        """Return the plugins."""
        return self._plugins

    def get_plugin(self, plugin_id: str) -> Optional[DynamicPlugin]:
        """Return a plugin by id."""
        return self._plugins.get(plugin_id)

    def add_plugin(self, plugin: DynamicPlugin) -> None:
        """Add a plugin."""
        self._plugins[plugin.id] = plugin

    def remove_plugin(self, plugin: DynamicPlugin) -> None:
        """Remove a plugin by id."""
        del self._plugins[plugin.id]


class WorkspaceInfo(BaseModel):
    """Represent a workspace."""

    name: str
    persistent: bool
    owners: List[str]
    visibility: VisibilityEnum
    description: Optional[str]
    icon: Optional[str]
    covers: Optional[List[str]]
    docs: Optional[str]
    allow_list: Optional[List[str]]
    deny_list: Optional[List[str]]
    _logger: Optional[logging.Logger] = PrivateAttr(default_factory=lambda: logger)
    _plugins: Dict[str, DynamicPlugin] = PrivateAttr(
        default_factory=lambda: {}
    )  # name: plugin
    _services: Dict[str, ServiceInfo] = PrivateAttr(default_factory=lambda: {})
    _event_bus: EventBus = PrivateAttr(default_factory=lambda: EventBus())

    def get_logger(self) -> Optional[logging.Logger]:
        """Return the logger."""
        return self._logger

    def set_logger(self, workspace_logger: logging.Logger) -> None:
        """Return the logger."""
        self._logger = workspace_logger

    def get_plugins(self) -> Dict[str, Any]:
        """Return the plugins."""
        return self._plugins

    def get_plugin(self, plugin_name: str) -> Optional[DynamicPlugin]:
        """Return a plugin."""
        return self._plugins.get(plugin_name)

    def add_plugin(self, plugin: DynamicPlugin) -> None:
        """Set a plugin."""
        if plugin.name in self._plugins:
            # kill the plugin if already exist
            asyncio.ensure_future(plugin.terminate())
        self._plugins[plugin.name] = plugin

    def remove_plugin(self, plugin: DynamicPlugin) -> None:
        """Remove a plugin form the workspace."""
        plugin_name = plugin.name
        if plugin_name not in self._plugins:
            raise KeyError(f"Plugin not fould (name={plugin_name})")
        plugin = self._plugins[plugin_name]
        del self._plugins[plugin.name]

    def get_services_by_plugin(self, plugin: DynamicPlugin) -> List[ServiceInfo]:
        """Get services by plugin."""
        return [
            self._services[k]
            for k in self._services
            if self._services[k]._provider == plugin
        ]

    def get_services(self) -> Dict[str, ServiceInfo]:
        """Return the services."""
        return self._services

    def add_service(self, service_name: str, service: ServiceInfo) -> None:
        """Add a service."""
        self._services[service_name] = service

    def get_service(self, service_name: str) -> ServiceInfo:
        """Get a service."""
        return self._services[service_name]

    def remove_service(self, service_name: str) -> None:
        """Remove a service."""
        del self._services[service_name]

    def get_event_bus(self):
        """Get the workspace event bus"""
        return self._event_bus
