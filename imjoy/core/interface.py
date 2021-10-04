"""Provide interface functions for the core."""
import logging
import sys
from functools import partial
from typing import Optional
import uuid
import pkg_resources

from imjoy.core import (
    UserInfo,
    VisibilityEnum,
    TokenConfig,
    WorkspaceInfo,
    current_plugin,
    current_user,
    current_workspace,
    get_all_workspace,
    get_workspace,
    register_workspace,
)
from imjoy.core.auth import check_permission, generate_presigned_token
from imjoy.core.plugin import DynamicPlugin
from imjoy.utils import dotdict
from imjoy.core.connection import BasicConnection

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)


# Add public workspace
register_workspace(
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


class CoreInterface:
    """Represent the interface of the ImJoy core."""

    # pylint: disable=no-self-use, protected-access

    def __init__(self, app, event_bus, imjoy_api=None, app_controller=None):
        """Set up instance."""
        self.event_bus = event_bus
        self.current_plugin = current_plugin
        self.current_user = current_user
        self.current_workspace = current_workspace
        self.app = app
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
                "get_workspace": self.get_workspace,
                "getWorkspace": self.get_workspace,
            }
        )
        self._imjoy_api.update(imjoy_api)

        # run server extensions
        for entry_point in pkg_resources.iter_entry_points(
            "imjoy_core_server_extension"
        ):
            user_info = UserInfo(
                id=entry_point.name,
                email=None,
                parent=None,
                roles=[],
                scopes=[],
                expires_at=None,
            )
            workspace = WorkspaceInfo(
                name=str(uuid.uuid4()) + entry_point.name,
                owners=[user_info.id],
                visibility=VisibilityEnum.protected,
                persistent=False,
            )
            connection = BasicConnection(lambda x: x)
            plugin = DynamicPlugin(
                {"workspace": workspace.name, "name": entry_point.name},
                self.get_interface(),
                self.get_codecs(),
                connection,
                workspace,
                user_info,
            )
            current_user.set(user_info)
            current_workspace.set(workspace)
            current_plugin.set(plugin)
            try:
                setup_extension = entry_point.load()
                setup_extension(self._imjoy_api)
            except Exception:
                logger.exception("Failed to setup extension: %s", entry_point.name)
                raise

        # Create root user
        self.root_user = UserInfo(
            id="root",
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
        register_workspace(self.root_workspace)

    def register_router(self, router):
        self.app.include_router(router)

    def register_interface(self, name, func):
        """Register a interface function."""
        assert callable(func)
        self._imjoy_api[name] = func

    def register_service(self, service: dict):
        """Register a service."""
        plugin = current_plugin.get()
        workspace = current_workspace.get()
        id = f'{workspace.name}/{service["name"]}'
        if "name" not in service or "type" not in service:
            raise Exception("Service should at least contain `name` and `type`")

        # TODO: check if it's already exists
        config = service.get("config", {})
        assert isinstance(config, dict), "service.config must be a dictionary"
        if config.get("name") and service["name"] != config.get("name"):
            raise Exception("Service name should match the one in the service.config.")
        if config.get("type") and service["type"] != config.get("type"):
            raise Exception("Service type should match the one in the service.config.")

        config["name"] = service["name"]
        config["type"] = service["type"]
        config["workspace"] = workspace.name
        config["id"] = id
        config["provider"] = plugin.name
        config["provider_id"] = plugin.id
        service["config"] = config
        service["_rintf"] = True
        # Note: service can set its `visiblity` to `public` or `protected`
        workspace._services[service["name"]] = service
        return id

    def list_plugins(self):
        """List all plugins in the workspace."""
        workspace = current_workspace.get()
        return [name for name in workspace._plugins]

    async def get_plugin(self, name):
        """Return a plugin by its name."""
        workspace = current_workspace.get()

        if name in workspace._plugins:
            return await workspace._plugins[name].get_api()
        raise Exception(f"Plugin {name} not found")

    async def get_service(self, service_id):
        if isinstance(service_id, dict):
            service_id = service_id["id"]
        if "/" not in service_id:
            raise Exception(
                "Invalid service_id format, it must be <workspace>/<service_name>"
            )
        ws, service_name = service_id.split("/")
        workspace = get_workspace(ws)
        if not workspace:
            raise Exception(f"Service not found: {service_id} (workspace unavailable)")

        service = workspace._services.get(service_name)
        user_info = current_user.get()
        if (
            not check_permission(workspace, user_info)
            and service["config"]["visibility"] != "public"
        ):
            raise Exception(f"Permission denied: {service_id}")

        if not service:
            raise Exception(f"Service not found: {service_id}")
        return service

    def list_services(self, query: Optional[dict] = None):
        """Return a list of services based on the query."""
        # if workspace is not set, then it means current workspace
        # if workspace = *, it means search gloabally
        # otherwise, it search the specified workspace
        user_info = current_user.get()
        if query is None:
            query = {"workspace": "*"}

        ws = query.get("workspace")
        if ws:
            del query["workspace"]
        if ws == "*":
            ret = []
            for workspace in get_all_workspace():
                can_access_ws = check_permission(workspace, user_info)
                for k in workspace._services:
                    service = workspace._services[k]
                    # To access the service, it should be public or owned by the user
                    if (
                        not can_access_ws
                        and service["config"]["visibility"] != "public"
                    ):
                        continue
                    match = True
                    for key in query:
                        if service["config"][key] != query[key]:
                            match = False
                    if match:
                        ret.append(service["config"])
            return ret
        elif ws is not None:
            workspace = get_workspace(ws)
        else:
            workspace = current_workspace.get()
        ret = []
        for k in workspace._services:
            service = workspace._services[k]
            match = True
            for key in query:
                if service["config"][key] != query[key]:
                    match = False
            if match:
                ret.append(service["config"])

        if workspace is None:
            raise Exception("Workspace not found: {ws}")

        return ret

    def info(self, msg):
        """Log a plugin message."""
        plugin = current_plugin.get()
        logger.info("%s: %s", plugin.name, msg)
        if plugin.workspace._logger:
            plugin.workspace._logger.info("%s: %s", plugin.name, msg)

    def warning(self, msg):
        """Log a plugin message (warning)."""
        plugin = current_plugin.get()
        if plugin.workspace._logger:
            plugin.workspace._logger.warning("%s: %s", plugin.name, msg)

    def error(self, msg):
        """Log a plugin error message (error)."""
        plugin = current_plugin.get()
        if plugin.workspace._logger:
            plugin.workspace._logger.error("%s: %s", plugin.name, msg)

    def critical(self, msg):
        """Log a plugin error message (critical)."""
        plugin = current_plugin.get()
        if plugin.workspace._logger:
            plugin.workspace._logger.critical("%s: %s", plugin.name, msg)

    def generate_token(self, config: Optional[dict] = None):
        """Generate a token for the current workspace."""
        workspace = current_workspace.get()
        config = config or {}
        if "scopes" in config and config["scopes"] != [workspace.name]:
            raise Exception("Scopes must be empty or contains only the workspace name.")
        config["scopes"] = [workspace.name]
        token_config = TokenConfig.parse_obj(config)
        token = generate_presigned_token(current_user.get(), token_config)
        return token

    def create_workspace(self, config: dict):
        """Create a new workspace."""
        config["persistent"] = config.get("persistent") or False
        workspace = WorkspaceInfo.parse_obj(config)
        if get_workspace(workspace.name):
            raise Exception(f"Workspace {workspace.name} already exists.")
        if workspace.authorizer:
            raise Exception("Workspace authorizer is not supported yet.")
        user_info = current_user.get()
        # make sure we add the user's email to owners
        _id = user_info.email or user_info.id
        if _id not in workspace.owners:
            workspace.owners.append(_id)
        workspace.owners = [o.strip() for o in workspace.owners if o.strip()]
        user_info.scopes.append(workspace.name)
        register_workspace(workspace)
        return self.get_workspace(workspace.name)

    def _update_workspace(self, name, config: dict):
        """Bind the context to the generated workspace."""
        if not name:
            raise Exception("Workspace name is not specified.")
        if not get_workspace(name):
            raise Exception(f"Workspace {name} not found")
        workspace = get_workspace(name)
        user_info = current_user.get()
        if not check_permission(workspace, user_info):
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

    def get_workspace(self, name: str):
        """Bind the context to the generated workspace."""
        workspace = get_workspace(name)
        if not workspace:
            raise Exception(f"Workspace {name} not found")
        user_info = current_user.get()
        if not check_permission(workspace, user_info):
            raise PermissionError(f"Permission denied for workspace {name}")

        interface = self.get_interface()
        bound_interface = {}
        for key in interface:
            if callable(interface[key]):

                def wrap_func(func, *args, **kwargs):
                    try:
                        workspace_bk = current_workspace.get()
                    except LookupError:
                        workspace_bk = None
                    ret = None
                    try:
                        current_workspace.set(workspace)
                        ret = func(*args, **kwargs)
                    except Exception as exp:
                        raise exp
                    finally:
                        current_workspace.set(workspace_bk)
                    return ret

                bound_interface[key] = partial(wrap_func, interface[key])
                bound_interface[key].__name__ = key  # required for imjoy-rpc
            else:
                bound_interface[key] = interface[key]
        bound_interface["config"] = {"workspace": name}
        bound_interface["set"] = partial(self._update_workspace, name)
        bound_interface["_rintf"] = True
        self.event_bus.emit("user_entered_workspace", (user_info, workspace))
        return bound_interface

    def get_workspace_as_root(self, name="root"):
        """Get a workspace api as root user."""
        current_user.set(self.root_user)
        return dotdict(self.get_workspace(name))

    async def get_plugin_as_root(self, name, workspace):
        """Get a plugin api as root user."""
        current_user.set(self.root_user)
        workspace = get_workspace(workspace)
        if not workspace:
            raise Exception(f"Workspace {workspace} does not exist.")
        current_workspace.set(workspace)
        return dotdict(await self.get_plugin(name))

    def get_interface(self):
        """Return the interface."""
        return self._imjoy_api.copy()

    def register_codec(self, config):
        """Register a codec"""
        assert "name" in config
        assert "encoder" in config or "decoder" in config
        if "type" in config:
            for tp in list(self._codecs.keys()):
                codec = self._codecs[tp]
                if codec.type == config["type"] or tp == config["name"]:
                    logger.info("Removing duplicated codec: " + tp)
                    del self._codecs[tp]

        self._codecs[config["name"]] = dotdict(config)

    def get_codecs(self):
        """Return registered codecs for rpc"""
        return self._codecs
