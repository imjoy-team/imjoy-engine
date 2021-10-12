"""Provide the ImJoy core API interface."""
from enum import Enum
import logging
import sys
from typing import Any, Dict, List, Optional

from pydantic import (  # pylint: disable=no-name-in-module
    BaseModel,
    EmailStr,
    PrivateAttr,
    Extra,
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

    def emit(self, event_name, *data):
        """Trigger an event."""
        for func in self._callbacks.get(event_name, []):
            func(*data)

    def off(self, event_name, func):
        """Remove an event callback."""
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
    _sessions: List[str] = PrivateAttr(default_factory=lambda: [])  # session ids

    def get_metadata(self) -> Dict[str, Any]:
        """Return the metadata."""
        return self._metadata

    def get_plugins(self) -> Dict[str, DynamicPlugin]:
        """Return the plugins."""
        return self._plugins

    def get_plugin(self, plugin_name: str) -> Optional[DynamicPlugin]:
        """Return a plugin."""
        return self._plugins.get(plugin_name)

    def set_plugin(self, plugin_name: str, plugin: DynamicPlugin) -> None:
        """Set a plugin."""
        self._plugins[plugin_name] = plugin

    def remove_plugin(self, plugin_name: str) -> None:
        """Remove a plugin."""
        del self._plugins[plugin_name]

    def get_sessions(self) -> List[str]:
        """Return the sessions."""
        return self._sessions

    def add_session(self, session: str) -> None:
        """Add a session."""
        self._sessions.append(session)

    def remove_session(self, session: str) -> None:
        """Remove a session."""
        self._sessions.remove(session)


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

    def set_plugin(self, plugin_name: str, plugin: DynamicPlugin) -> None:
        """Set a plugin."""
        self._plugins[plugin_name] = plugin

    def remove_plugin(self, plugin_name: str) -> None:
        """Remove a plugin."""
        del self._plugins[plugin_name]

    def get_services(self) -> Dict[str, ServiceInfo]:
        """Return the services."""
        return self._services

    def set_service(self, service_name: str, service: ServiceInfo) -> None:
        """Set a service."""
        self._services[service_name] = service

    def remove_service(self, service_name: str) -> None:
        """Remove a service."""
        del self._services[service_name]
