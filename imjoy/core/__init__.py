"""Provide the ImJoy core API interface."""
from enum import Enum
import logging
import sys
from typing import Any, Callable, Dict, List, Tuple, Optional

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

    def get_plugin(self, plugin_id: str) -> Optional[DynamicPlugin]:
        """Return a plugin by id."""
        return self._plugins.get(plugin_id)

    def add_plugin(self, plugin: DynamicPlugin) -> None:
        """Add a plugin."""
        self._plugins[plugin.id] = plugin

    def remove_plugin(self, plugin_id: str) -> None:
        """Remove a plugin by id."""
        del self._plugins[plugin_id]

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
    _event_handlers: Dict[str, List[Tuple[Any]]] = PrivateAttr(
        default_factory=lambda: {}
    )

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
        self._plugins[plugin.name] = plugin

    def remove_plugin(self, plugin_name: str) -> None:
        """Remove a plugin form the workspace."""
        if plugin_name not in self._plugins:
            raise KeyError(f"Plugin not fould (name={plugin_name})")
        plugin = self._plugins[plugin_name]
        del self._plugins[plugin.name]
        # remove the services that registered by this plugin
        # note: we might need to emit service_unregister event
        # pylint: disable=protected-access
        self._services = {
            k: self._services[k]
            for k in self._services
            if self._services[k]._provider != plugin
        }
        # remove event hanlders
        self._event_handlers = {
            evt: self._event_handlers[evt]
            for evt in self._event_handlers
            if self._event_handlers[evt][0] != plugin
        }

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

    def add_event_hander(
        self,
        plugin: DynamicPlugin,
        event: str,
        handler: Callable,
        run_once: bool = False,
    ) -> None:
        """Register an event handler."""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        # a tuple with the plugin, the event handler,
        # or whether remove it after triggered
        self._event_handlers[event].append((plugin, handler, run_once))

    def remove_event_hander(self, plugin: DynamicPlugin, event: str) -> None:
        """Register an event handler."""
        if event not in self._event_handlers:
            raise KeyError("No event handler found for " + event)
        # Remove all the events belongs to the current plugin
        self._event_handlers[event] = [
            v for v in self._event_handlers[event] if v[0] != plugin
        ]

    def fire_event(self, plugin: DynamicPlugin, event: str, data: Any = None) -> None:
        """Execute the event handlers for an event."""
        if event not in self._event_handlers:
            return
        for (_, handler, run_once) in self._event_handlers[event].copy():
            try:
                handler(
                    {
                        "target": {"plugin_name": plugin.name, "plugin_id": plugin.id},
                        "data": data,
                    }
                )
            # pylint: disable=broad-except
            except Exception as exp:
                plugin.log(f"Failed to handle event '{event}', error: {exp}")

            # Remove the handler
            if run_once:
                self._event_handlers[event] = [
                    v for v in self._event_handlers[event] if v[1] != handler
                ]
