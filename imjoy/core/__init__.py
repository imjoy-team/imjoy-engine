"""Provide the ImJoy core API interface."""
from enum import Enum
import logging
import sys
from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional

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


class ServiceInfo(BaseModel):
    """Represent service."""

    config: Dict[str, Any]
    name: str
    type: str
    visibility: VisibilityEnum = VisibilityEnum.protected
    _provider: DynamicPlugin = PrivateAttr(default_factory=lambda: None)

    class Config:
        """Set the config for pydantic."""

        extra = Extra.allow

    def set_provider(self, provider: DynamicPlugin) -> None:
        """Return the plugins."""
        self._provider = provider


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
    authorizer: Optional[str]
    _logger: Optional[logging.Logger] = PrivateAttr(default_factory=lambda: logger)
    _authorizer: Optional[Callable] = PrivateAttr(default_factory=lambda: None)
    _plugins: Dict[str, DynamicPlugin] = PrivateAttr(
        default_factory=lambda: {}
    )  # name: plugin
    _services: Dict[str, ServiceInfo] = PrivateAttr(default_factory=lambda: {})

    def get_logger(self) -> Optional[logging.Logger]:
        """Return the logger."""
        return self._logger

    def get_authorizer(self) -> Optional[Callable]:
        """Return the authorizer."""
        return self._authorizer

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


event_bus = EventBus()
current_user = ContextVar("current_user")
current_plugin = ContextVar("current_plugin")
current_workspace = ContextVar("current_workspace")
all_sessions: Dict[str, UserInfo] = {}  # sid:user_info
all_users: Dict[str, UserInfo] = {}  # uid:user_info
_all_workspaces: Dict[str, WorkspaceInfo] = {}  # wid:workspace_info


def get_all_workspace():
    """Return all workspaces."""
    return list(_all_workspaces.values())


def is_workspace_registered(ws):
    """Return true if workspace is registered."""
    if ws in _all_workspaces.values():
        return True
    return False


def get_workspace(name):
    """Return the workspace."""
    if name in _all_workspaces:
        return _all_workspaces[name]
    return None


def register_workspace(ws):
    """Register the workspace."""
    if ws.name in _all_workspaces:
        raise Exception(
            f"Another workspace with the same name {ws.name} already exist."
        )
    _all_workspaces[ws.name] = ws
    event_bus.emit("workspace_registered", ws)


def unregister_workspace(name):
    """Unregister the workspace."""
    if name not in _all_workspaces:
        raise Exception(f"Workspace has not been registered: {name}")
    ws = _all_workspaces[name]
    del _all_workspaces[name]
    event_bus.emit("workspace_unregistered", ws)
