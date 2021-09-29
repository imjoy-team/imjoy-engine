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
    all_workspaces,
    current_plugin,
    current_user,
    current_workspace,
)
from imjoy.core.auth import check_permission, generate_presigned_token
from imjoy.core.plugin import DynamicPlugin
from imjoy.utils import dotdict
from imjoy.core.connection import BasicConnection

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)


# Add test workspace
all_workspaces["test"] = WorkspaceInfo.parse_obj(
    {
        "name": "test",
        "persistent": True,
        "owners": ["admin"],
        "allow_list": [],
        "deny_list": [],
        "visibility": "public",
    }
)


class CoreInterface:
    """Represent the interface of the ImJoy core."""

    # pylint: disable=no-self-use, protected-access

    def __init__(self, imjoy_api=None, app_controller=None):
        """Set up instance."""
        self.app_controller = app_controller
        imjoy_api = imjoy_api or {}
        self.imjoy_api = dotdict(
            {
                "_rintf": True,
                "log": self.log,
                "error": self.error,
                "getAppController": self.get_app_controller,
                "get_app_controller": self.get_app_controller,
                "registerService": self.register_service,
                "register_service": self.register_service,
                "getServices": self.get_services,
                "get_services": self.get_services,
                "utils": {},
                "getPlugins": self.get_plugins,
                "get_plugins": self.get_plugins,
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
        self.imjoy_api.update(imjoy_api)

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
                connection,
                workspace,
            )
            current_user.set(user_info)
            current_workspace.set(workspace)
            current_plugin.set(plugin)
            try:
                setup_extension = entry_point.load()
                setup_extension(self.imjoy_api)
            except Exception:
                logger.exception("Failed to setup extension: %s", entry_point.name)
                raise

    def get_app_controller(self):
        """Provide the server app controller."""
        if self.app_controller:
            return self.app_controller.get_public_api()
        else:
            raise Exception("Server app controller was disabled")

    def register_service(self, service: dict):
        """Register a service."""
        plugin = current_plugin.get()
        workspace = current_workspace.get()
        service["provider"] = plugin.name
        service["providerId"] = plugin.id
        service["_rintf"] = True
        workspace._services.append(service)

    def get_plugins(self):
        """Return all plugin in the workspace."""
        workspace = current_workspace.get()
        return [workspace._plugins[name].api for name in workspace._plugins]

    def get_plugin(self, name):
        """Return a plugin by its name."""
        workspace = current_workspace.get()

        if name in workspace._plugins:
            return workspace._plugins[name].api
        raise Exception(f"Plugin {name} not found")

    def get_services(self, query: dict):
        """Return a list of services based on the query."""
        workspace = current_workspace.get()
        ret = []
        for service in workspace._services:
            match = True
            for key in query:
                if service[key] != query[key]:
                    match = False
            if match:
                ret.append(service)
        return ret

    def log(self, msg):
        """Log a plugin message."""
        plugin = current_plugin.get()
        logger.info("%s: %s", plugin.name, msg)

    def error(self, msg):
        """Log a plugin error message."""
        plugin = current_plugin.get()
        logger.error("%s: %s", plugin.name, msg)

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
        if workspace.name in all_workspaces:
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
        all_workspaces[workspace.name] = workspace
        return self.get_workspace(workspace.name)

    def _update_workspace(self, name, config: dict):
        """Bind the context to the generated workspace."""
        if not name:
            raise Exception("Workspace name is not specified.")
        if name not in all_workspaces:
            raise Exception(f"Workspace {name} not found")
        workspace = all_workspaces[name]
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
        if name not in all_workspaces:
            raise Exception(f"Workspace {name} not found")
        workspace = all_workspaces[name]
        user_info = current_user.get()
        if not check_permission(workspace, user_info):
            raise PermissionError(f"Permission denied for workspace {name}")

        interface = self.get_interface()
        bound_interface = {}
        for key in interface:
            if callable(interface[key]):

                def wrap_func(func, *args, **kwargs):
                    workspace_bk = current_workspace.get()
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
        return bound_interface

    def get_interface(self):
        """Return the interface."""
        return self.imjoy_api.copy()
