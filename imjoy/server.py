"""Provide the server."""
import asyncio
import os
import uuid
from contextvars import copy_context
from os import environ as env
from typing import Union

import socketio
import uvicorn
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from imjoy import __version__ as VERSION
from imjoy.core import (
    UserInfo,
    VisibilityEnum,
    WorkspaceInfo,
    all_users,
    all_sessions,
    current_user,
    current_plugin,
    current_workspace,
    all_workspaces,
)
from imjoy.core.auth import parse_token, check_permission
from imjoy.core.connection import BasicConnection
from imjoy.core.interface import CoreInterface
from imjoy.core.plugin import DynamicPlugin

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)


def initialize_socketio(sio, core_api):
    """Initialize socketio."""
    # pylint: disable=too-many-statements, unused-variable, protected-access

    @sio.event
    async def connect(sid, environ):
        """Handle event called when a socketio client is connected to the server."""
        if "HTTP_AUTHORIZATION" in environ:
            try:
                authorization = environ["HTTP_AUTHORIZATION"]  # JWT token
                user_info = parse_token(authorization)
                uid = user_info["user_id"]
                email = user_info["email"]
                roles = user_info["roles"]
                parent = user_info.get("parent")
                scopes = user_info.get("scopes") or []
                expires_at = user_info.get("expires_at")
            except Exception as err:  # pylint: disable=broad-except
                logger.exception("Authentication failed: %s", err)
                # The connect event handler can return False
                # to reject the connection with the client.
                return False
            logger.info("User connected: %s", uid)
        else:
            uid = str(uuid.uuid4())
            email = None
            roles = []
            parent = None
            scopes = []
            expires_at = None
            logger.info("Anonymized User connected: %s", uid)

        if uid not in all_users:
            all_users[uid] = UserInfo(
                id=uid,
                email=email,
                parent=parent,
                roles=roles,
                scopes=scopes,
                expires_at=expires_at,
            )
        all_users[uid]._sessions.append(sid)
        all_sessions[sid] = all_users[uid]

    @sio.event
    async def echo(sid, data):
        """Echo service for testing."""
        return data

    @sio.event
    async def register_plugin(sid, config):
        user_info = all_sessions[sid]
        ws = config.get("workspace") or user_info.id
        config["workspace"] = ws
        config["name"] = config.get("name") or str(uuid.uuid4())
        if ws in all_workspaces:
            workspace = all_workspaces[ws]
        else:
            if ws == user_info.id:
                # create the user workspace automatically
                workspace = WorkspaceInfo(
                    name=ws,
                    owners=[user_info.id],
                    visibility=VisibilityEnum.protected,
                    persistent=(config.get("persistent") is True),
                )
                all_workspaces[ws] = workspace
            else:
                return {"success": False, "detail": f"Workspace {ws} does not exist."}

        if user_info.id != ws and not check_permission(workspace, user_info):
            return {
                "success": False,
                "detail": f"Permission denied for workspace: {ws}",
            }

        name = config["name"].replace("/", "-")  # prevent hacking of the plugin name
        plugin_id = f"{ws}/{name}"
        config["id"] = plugin_id
        sio.enter_room(sid, plugin_id)

        async def send(data):
            await sio.emit(
                "plugin_message",
                data,
                room=plugin_id,
            )

        connection = BasicConnection(send)
        plugin = DynamicPlugin(config, core_api.get_interface(), connection, workspace)

        user_info._plugins[plugin.id] = plugin
        if plugin.name in workspace._plugins:
            # kill the plugin if already exist
            asyncio.ensure_future(plugin.terminate(True))
            del user_info._plugins[plugin.id]
        workspace._plugins[plugin.name] = plugin
        logger.info("New plugin registered successfully (%s)", plugin_id)
        return {"success": True, "plugin_id": plugin_id}

    @sio.event
    async def plugin_message(sid, data):
        user_info = all_sessions[sid]
        plugin_id = data["plugin_id"]
        ws, name = os.path.split(plugin_id)
        if ws not in all_workspaces:
            return {"success": False, "detail": f"Workspace not found: {ws}"}
        workspace = all_workspaces[ws]
        if user_info.id != ws and not check_permission(workspace, user_info):
            logger.error(
                "Permission denied: workspace=%s, user_id=%s", workspace, user_info.id
            )
            return {"success": False, "detail": "Permission denied"}

        plugin = workspace._plugins.get(name)
        if not plugin:
            logger.warning("Plugin %s not found in workspace %s", name, workspace.name)
            return {
                "success": False,
                "detail": f"Plugin {name} not found in workspace {workspace.name}",
            }

        current_user.set(user_info)
        current_plugin.set(plugin)
        current_workspace.set(workspace)
        ctx = copy_context()
        ctx.run(plugin.connection.handle_message, data)
        return {"success": True}

    @sio.event
    async def disconnect(sid):
        """Event handler called when the client is disconnected."""
        user_info = all_sessions[sid]
        all_users[user_info.id]._sessions.remove(sid)
        # if the user has no more all_sessions
        if not all_users[user_info.id]._sessions:
            del all_users[user_info.id]
            for pid in list(user_info._plugins.keys()):
                plugin = user_info._plugins[pid]
                # TODO: how to allow plugin running when the user disconnected
                # we will also need to handle the case when the user login again
                # the plugin should be reclaimed for the user
                del plugin.workspace._plugins[plugin.name]
                # if there is no plugins in the workspace then we remove it
                if not plugin.workspace._plugins and not plugin.workspace.persistent:
                    del all_workspaces[plugin.workspace.name]
                asyncio.ensure_future(plugin.terminate())
                del user_info._plugins[pid]

                # TODO: if a workspace has no plugins anymore
                # we should destroy it completely
                # Importantly, if we want to recycle the workspace name,
                # we need to make sure we don't mess up with the permission
                # with the plugins of the previous owners
                for service in plugin.workspace._services.copy():
                    if service.providerId == plugin.id:
                        plugin.workspace._services.remove(service)
        del all_sessions[sid]


def create_application(allow_origins, base_path) -> FastAPI:
    """Set up the server application."""
    # pylint: disable=unused-variable, protected-access

    app = FastAPI(
        title="ImJoy Core Server",
        description=(
            "A server for managing imjoy plugins and \
                enabling remote procedure calls"
        ),
        version=VERSION,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.get(base_path)
    async def root():
        return {
            "name": "ImJoy Core Server",
            "version": VERSION,
            "all_users": {u: all_users[u]._sessions for u in all_users},
            "all_workspaces": {
                w.name: len(w._plugins) for w in all_workspaces.values()
            },
        }

    return app


def setup_socketio_server(
    app: FastAPI,
    base_path: str = "/",
    allow_origins: Union[str, list] = "*",
) -> None:
    """Set up the socketio server."""
    socketio_path = base_path.rstrip("/") + "/socket.io"

    @app.get(base_path.rstrip("/") + "/liveness")
    async def liveness(req: Request) -> JSONResponse:
        try:
            await sio.emit("liveness")
        except Exception:  # pylint: disable=broad-except
            return JSONResponse({"status": "DOWN"}, status_code=503)
        return JSONResponse({"status": "OK"})

    if allow_origins == ["*"]:
        allow_origins = "*"
    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=allow_origins)

    _app = socketio.ASGIApp(socketio_server=sio, socketio_path=socketio_path)

    app.mount("/", _app)
    app.sio = sio
    core_api = CoreInterface()
    initialize_socketio(sio, core_api)

    return sio


def start_server(args):
    """Start the socketio server."""
    if args.allow_origin:
        allow_origin = args.allow_origin.split(",")
    else:
        allow_origin = env.get("ALLOW_ORIGINS", "*").split(",")
    application = create_application(allow_origin, args.base_path)
    setup_socketio_server(
        application, base_path=args.base_path, allow_origins=allow_origin
    )
    if args.host == "127.0.0.1" or args.host == "localhost":
        print(
            "***Note: If you want to enable access from another host,\
                 please start with `--host=0.0.0.0`.***"
        )
    uvicorn.run(application, host=args.host, port=int(args.port))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="host for the socketio server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="port for the socketio server",
    )
    parser.add_argument(
        "--allow-origin",
        type=str,
        default="*",
        help="origins for the socketio server",
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default="/",
        help="the base path for the server",
    )
    opt = parser.parse_args()
    start_server(opt)
