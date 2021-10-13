"""Provide interface functions for the core."""
import logging
import sys
from contextvars import ContextVar
from functools import partial
from typing import Dict, Optional

import pkg_resources
from starlette.routing import Mount

from imjoy.core import (
    EventBus,
    ServiceInfo,
    TokenConfig,
    UserInfo,
    VisibilityEnum,
    WorkspaceInfo,
)
from imjoy.core.auth import generate_presigned_token
from imjoy.core.connection import BasicConnection
from imjoy.core.plugin import DynamicPlugin
from imjoy.utils import dotdict

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)


class CoreInterface:
    """Represent the interface of the ImJoy core."""

    # pylint: disable=no-self-use, too-many-instance-attributes, too-many-public-methods

    def __init__(self, app, imjoy_api=None, app_controller=None):
        """Set up instance."""
        self.event_bus = EventBus()
        self.current_user = ContextVar("current_user")
        self.current_plugin = ContextVar("current_plugin")
        self.current_workspace = ContextVar("current_workspace")
        self.all_sessions: Dict[str, UserInfo] = {}  # sid:user_info
        self.all_users: Dict[str, UserInfo] = {}  # uid:user_info
        self._all_workspaces: Dict[str, WorkspaceInfo] = {}  # wid:workspace_info
        self._app = app
        self.app_controller = app_controller
        imjoy_api = imjoy_api or {}
        self._codecs = {}
        self._imjoy_api = dotdict(
            {
                "_rintf": True,
                "log": self.info,
                "info": self.info,
                "error": self.error,
                "warning": self.warning,
                "critical": self.critical,
                "registerService": self.register_service,
                "register_service": self.register_service,
                "listServices": self.list_services,
                "list_services": self.list_services,
                "getService": self.get_service,
                "get_service": self.get_service,
                "utils": {},
                "listPlugins": self.list_plugins,
                "list_plugins": self.list_plugins,
                "getPlugin": self.get_plugin,
                "get_plugin": self.get_plugin,
                "generateToken": self.generate_token,
                "generate_token": self.generate_token,
                "create_workspace": self.create_workspace,
                "createWorkspace": self.create_workspace,
                "get_workspace": self.get_workspace_interface,
                "getWorkspace": self.get_workspace_interface,
                "list_workspaces": self.list_workspaces,
                "listWorkspaces": self.list_workspaces,
                "on": self.on,
                "once": self.once,
                "off": self.off,
                "emit": self.emit,
                "disconnect": self.disconnect,
            }
        )
        self._imjoy_api.update(imjoy_api)

        # Add public workspace
        self.register_workspace(
            WorkspaceInfo.parse_obj(
                {
                    "name": "public",
                    "persistent": True,
                    "owners": ["root"],
                    "allow_list": [],
                    "deny_list": [],
                    "visibility": "public",
                }
            )
        )

        # Create root user
        self.root_user = UserInfo(
            id="root",
            is_anonymous=False,
            email=None,
            parent=None,
            roles=[],
            scopes=[],
            expires_at=None,
        )
        # Create root workspace
        self.root_workspace = WorkspaceInfo(
            name="root",
            owners=["root"],
            visibility=VisibilityEnum.protected,
            persistent=True,
        )
        self.register_workspace(self.root_workspace)
        self.load_extensions()

    def on(self, event, handler):
        """Register an event handler."""
        workspace = self.current_workspace.get()
        plugin = self.current_plugin.get()
        workspace.add_event_hander(plugin, event, handler, run_once=False)

    def once(self, event, handler):
        """Register an event handler that run only once."""
        workspace = self.current_workspace.get()
        plugin = self.current_plugin.get()
        workspace.add_event_hander(plugin, event, handler, run_once=True)

    def off(self, event):
        """Remove an event handler."""
        workspace = self.current_workspace.get()
        plugin = self.current_plugin.get()
        workspace.remove_event_hander(plugin, event)

    def emit(self, event, data=None):
        """Emit an event to the workspace."""
        workspace = self.current_workspace.get()
        plugin = self.current_plugin.get()
        workspace.fire_event(plugin, event, data)

    async def disconnect(
        self,
    ):
        """Disconnect from the workspace."""
        plugin = self.current_plugin.get()
        await plugin.terminate()

    def check_permission(self, workspace, user_info):
        """Check user permission for a workspace."""
        # pylint: disable=too-many-return-statements
        if isinstance(workspace, str):
            workspace = self.get_workspace(workspace)
            if not workspace:
                logger.warning("Workspace %s not found", workspace)
                return False

        # Make exceptions for root user, the children of root and test workspace
        if (
            user_info.id == "root"
            or user_info.parent == "root"
            or workspace.name == "public"
        ):
            return True

        if workspace.name == user_info.id:
            return True

        if user_info.parent:
            parent = self.all_users.get(user_info.parent)
            if not parent:
                return False
            if not self.check_permission(workspace, parent):
                return False
            # if the parent has access
            # and the workspace is in the scopes
            # then we allow the access
            if workspace.name in user_info.scopes:
                return True

        _id = user_info.email or user_info.id

        if _id in workspace.owners:
            return True

        if workspace.visibility == VisibilityEnum.public:
            if workspace.deny_list and user_info.email not in workspace.deny_list:
                return True
        elif workspace.visibility == VisibilityEnum.protected:
            if workspace.allow_list and user_info.email in workspace.allow_list:
                return True

        if "admin" in user_info.roles:
            logger.info(
                "Allowing access to %s for admin user %s", workspace.name, user_info.id
            )
            return True

        return False

    def get_all_workspace(self):
        """Return all workspaces."""
        return list(self._all_workspaces.values())

    def is_workspace_registered(self, ws):
        """Return true if workspace is registered."""
        if ws in self._all_workspaces.values():
            return True
        return False

    def get_workspace(self, name):
        """Return the workspace."""
        if name in self._all_workspaces:
            return self._all_workspaces[name]
        return None

    def register_workspace(self, ws):
        """Register the workspace."""
        if ws.name in self._all_workspaces:
            raise Exception(
                f"Another workspace with the same name {ws.name} already exist."
            )
        self._all_workspaces[ws.name] = ws
        self.event_bus.emit("workspace_registered", ws)

    def unregister_workspace(self, name):
        """Unregister the workspace."""
        if name not in self._all_workspaces:
            raise Exception(f"Workspace has not been registered: {name}")
        ws = self._all_workspaces[name]
        del self._all_workspaces[name]
        self.event_bus.emit("workspace_unregistered", ws)

    def load_extensions(self):
        """Load imjoy engine extensions."""
        # Support imjoy engine extensions
        # See how it works:
        # https://packaging.python.org/guides/creating-and-discovering-plugins/
        for entry_point in pkg_resources.iter_entry_points("imjoy_engine_extension"):
            connection = BasicConnection(lambda x: x)
            plugin = DynamicPlugin(
                {"workspace": self.root_workspace.name, "name": entry_point.name},
                self.get_interface(),
                self.get_codecs(),
                connection,
                self.root_workspace,
                self.root_user,
            )
            self.current_user.set(self.root_user)
            self.current_workspace.set(self.root_workspace)
            self.current_plugin.set(plugin)
            try:
                setup_extension = entry_point.load()
                setup_extension(self)
            except Exception:
                logger.exception("Failed to setup extension: %s", entry_point.name)
                raise

    def register_router(self, router):
        """Register a router."""
        self._app.include_router(router)

    def register_interface(self, name, func):
        """Register a interface function."""
        assert callable(func)
        self._imjoy_api[name] = func

    def register_service(self, service: dict):
        """Register a service."""
        plugin = self.current_plugin.get()
        workspace = self.current_workspace.get()
        service_id = f'{workspace.name}/{service["name"]}'
        if "name" not in service or "type" not in service:
            raise Exception("Service should at least contain `name` and `type`")

        # TODO: check if it's already exists
        service.config = service.get("config", {})
        assert isinstance(service.config, dict), "service.config must be a dictionary"
        service.config["id"] = service_id
        service.config["workspace"] = workspace.name
        formated_service = ServiceInfo.parse_obj(service)
        formated_service.set_provider(plugin)
        service_dict = formated_service.dict()
        if formated_service.config.require_context:
            for key in service_dict:
                if callable(service_dict[key]):

                    def wrap_func(func, *args, **kwargs):
                        user_info = self.current_user.get()
                        workspace = self.current_workspace.get()
                        kwargs["context"] = {
                            "user_id": user_info.id,
                            "email": user_info.email,
                            "is_anonymous": user_info.email,
                            "workspace": workspace.name,
                        }
                        return func(*args, **kwargs)

                    setattr(
                        formated_service, key, partial(wrap_func, service_dict[key])
                    )
        # service["_rintf"] = True
        # Note: service can set its `visibility` to `public` or `protected`
        workspace.add_service(formated_service.name, formated_service)
        self.event_bus.emit("service_registered", formated_service)
        return service_id

    def unregister_service(self, service_id):
        """Unregister an service."""
        workspace_name, service_name = service_id.split("/")
        workspace = self.current_workspace.get()
        assert (
            workspace.name == workspace_name
        ), f"The service {service_id} is not registered in the current workspace."
        service = workspace.get_service(service_name)
        workspace.remove_service(service_name)
        self.event_bus.emit("service_unregistered", service)

    def list_plugins(self):
        """List all plugins in the workspace."""
        workspace = self.current_workspace.get()
        return list(workspace.get_plugins())

    async def get_plugin(self, name):
        """Return a plugin by its name."""
        workspace = self.current_workspace.get()
        workspace_plugins = workspace.get_plugins()
        if name in workspace_plugins:
            return await workspace_plugins[name].get_api()
        raise Exception(f"Plugin {name} not found")

    async def get_service(self, service_id):
        """Return a service."""
        if isinstance(service_id, dict):
            service_id = service_id["id"]
        if "/" not in service_id:
            raise Exception(
                "Invalid service_id format, it must be <workspace>/<service_name>"
            )
        ws, service_name = service_id.split("/")
        workspace = self.get_workspace(ws)
        if not workspace:
            raise Exception(f"Service not found: {service_id} (workspace unavailable)")

        workspace_services = workspace.get_services()
        service = workspace_services.get(service_name)
        user_info = self.current_user.get()
        if (
            not self.check_permission(workspace, user_info)
            and service.config.visibility != VisibilityEnum.public
        ):
            raise Exception(f"Permission denied: {service_id}")

        if not service:
            raise Exception(f"Service not found: {service_id}")
        return service.dict()

    def list_workspaces(
        self,
    ):
        """List the workspaces for the user."""
        user_info = self.current_user.get()
        ret = []
        for workspace in self._all_workspaces.values():
            if self.check_permission(workspace, user_info):
                ret.append({"name": workspace.name})
        return ret

    def list_services(self, query: Optional[dict] = None):
        """Return a list of services based on the query."""
        # if workspace is not set, then it means current workspace
        # if workspace = *, it means search globally
        # otherwise, it search the specified workspace
        user_info = self.current_user.get()
        if query is None:
            query = {"workspace": "*"}

        ws = query.get("workspace")
        if ws:
            del query["workspace"]
        if ws == "*":
            ret = []
            for workspace in self.get_all_workspace():
                can_access_ws = self.check_permission(workspace, user_info)
                for service in workspace.get_services().values():
                    # To access the service, it should be public or owned by the user
                    if (
                        not can_access_ws
                        and service.config.visibility != VisibilityEnum.public
                    ):
                        continue
                    match = True
                    for key in query:
                        if getattr(service, key) != query[key]:
                            match = False
                    if match:
                        ret.append(service.get_summary())
            return ret
        if ws is not None:
            workspace = self.get_workspace(ws)
        else:
            workspace = self.current_workspace.get()
        ret = []
        workspace_services = workspace.get_services()
        for service in workspace_services.values():
            match = True
            for key in query:
                if getattr(service, key) != query[key]:
                    match = False
            if match:
                ret.append(service.get_summary())

        if workspace is None:
            raise Exception("Workspace not found: {ws}")

        return ret

    def info(self, msg):
        """Log a plugin message."""
        plugin = self.current_plugin.get()
        logger.info("%s: %s", plugin.name, msg)
        workspace_logger = plugin.workspace.get_logger()
        if workspace_logger:
            workspace_logger.info("%s: %s", plugin.name, msg)

    def warning(self, msg):
        """Log a plugin message (warning)."""
        plugin = self.current_plugin.get()
        workspace_logger = plugin.workspace.get_logger()
        if workspace_logger:
            workspace_logger.warning("%s: %s", plugin.name, msg)

    def error(self, msg):
        """Log a plugin error message (error)."""
        plugin = self.current_plugin.get()
        workspace_logger = plugin.workspace.get_logger()
        if workspace_logger:
            workspace_logger.error("%s: %s", plugin.name, msg)

    def critical(self, msg):
        """Log a plugin error message (critical)."""
        plugin = self.current_plugin.get()
        workspace_logger = plugin.workspace.get_logger()
        if workspace_logger:
            workspace_logger.critical("%s: %s", plugin.name, msg)

    def generate_token(self, config: Optional[dict] = None):
        """Generate a token for the current workspace."""
        workspace = self.current_workspace.get()
        user_info = self.current_user.get()
        config = config or {}
        if "scopes" in config and config["scopes"] != [workspace.name]:
            raise Exception("Scopes must be empty or contains only the workspace name.")
        config["scopes"] = [workspace.name]
        token_config = TokenConfig.parse_obj(config)
        scopes = token_config.scopes
        for scope in scopes:
            if not self.check_permission(scope, user_info):
                raise PermissionError(f"User has no permission to scope: {scope}")
        token = generate_presigned_token(user_info, token_config)
        return token

    def create_workspace(self, config: dict):
        """Create a new workspace."""
        user_info = self.current_user.get()
        config["persistent"] = config.get("persistent") or False
        if user_info.is_anonymous and config["persistent"]:
            raise Exception("Only registered user can create persistent workspace.")
        workspace = WorkspaceInfo.parse_obj(config)
        if self.get_workspace(workspace.name):
            raise Exception(f"Workspace {workspace.name} already exists.")
        user_info = self.current_user.get()
        # make sure we add the user's email to owners
        _id = user_info.email or user_info.id
        if _id not in workspace.owners:
            workspace.owners.append(_id)
        workspace.owners = [o.strip() for o in workspace.owners if o.strip()]
        user_info.scopes.append(workspace.name)
        self.register_workspace(workspace)
        return self.get_workspace_interface(workspace.name)

    def _update_workspace(self, name, config: dict):
        """Bind the context to the generated workspace."""
        if not name:
            raise Exception("Workspace name is not specified.")
        if not self.get_workspace(name):
            raise Exception(f"Workspace {name} not found")
        workspace = self.get_workspace(name)
        user_info = self.current_user.get()
        if not self.check_permission(workspace, user_info):
            raise PermissionError(f"Permission denied for workspace {name}")

        if "name" in config:
            raise Exception("Changing workspace name is not allowed.")

        # make sure all the keys are valid
        # TODO: verify the type
        for key in config:
            if key.startswith("_") or not hasattr(workspace, key):
                raise KeyError(f"Invalid key: {key}")

        for key in config:
            if not key.startswith("_") and hasattr(workspace, key):
                setattr(workspace, key, config[key])
        # make sure we add the user's email to owners
        _id = user_info.email or user_info.id
        if _id not in workspace.owners:
            workspace.owners.append(_id)
        workspace.owners = [o.strip() for o in workspace.owners if o.strip()]

    def get_workspace_interface(self, name: str):
        """Bind the context to the generated workspace."""
        workspace = self.get_workspace(name)
        if not workspace:
            raise Exception(f"Workspace {name} not found")
        user_info = self.current_user.get()
        if not self.check_permission(workspace, user_info):
            raise PermissionError(f"Permission denied for workspace {name}")

        interface = self.get_interface()
        bound_interface = {}
        for key in interface:
            if callable(interface[key]):

                def wrap_func(func, *args, **kwargs):
                    try:
                        workspace_bk = self.current_workspace.get()
                    except LookupError:
                        workspace_bk = None
                    ret = None
                    try:
                        self.current_workspace.set(workspace)
                        ret = func(*args, **kwargs)
                    except Exception as exp:
                        raise exp
                    finally:
                        self.current_workspace.set(workspace_bk)
                    return ret

                bound_interface[key] = partial(wrap_func, interface[key])
                bound_interface[key].__name__ = key  # required for imjoy-rpc
            else:
                bound_interface[key] = interface[key]
        bound_interface["config"] = {"workspace": name}
        bound_interface["set"] = partial(self._update_workspace, name)
        bound_interface["_rintf"] = True
        # Remove disconnect, since the plugin can call disconnect()
        # from their own workspace
        del bound_interface["disconnect"]
        self.event_bus.emit("user_entered_workspace", (user_info, workspace))
        return bound_interface

    def get_workspace_as_root(self, name="root"):
        """Get a workspace api as root user."""
        self.current_user.set(self.root_user)
        return dotdict(self.get_workspace_interface(name))

    async def get_plugin_as_root(self, name, workspace):
        """Get a plugin api as root user."""
        self.current_user.set(self.root_user)
        workspace = self.get_workspace(workspace)
        if not workspace:
            raise Exception(f"Workspace {workspace} does not exist.")
        self.current_workspace.set(workspace)
        return dotdict(await self.get_plugin(name))

    def get_interface(self):
        """Return the interface."""
        return self._imjoy_api.copy()

    def register_codec(self, config):
        """Register a codec."""
        assert "name" in config
        assert "encoder" in config or "decoder" in config
        if "type" in config:
            for codec_type, codec in list(self._codecs.items()):
                if codec.type == config["type"] or codec_type == config["name"]:
                    logger.info("Removing duplicated codec: %s", codec_type)
                    del self._codecs[codec_type]

        self._codecs[config["name"]] = dotdict(config)

    def get_codecs(self):
        """Return registered codecs for rpc."""
        return self._codecs

    def mount_app(self, path, app, name=None, priority=-1):
        """Mount an app to fastapi."""
        route = Mount(path, app, name=name)
        # The default priority is -1 which assumes the last one is websocket
        self._app.routes.insert(priority, route)
