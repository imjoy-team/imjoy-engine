"""Provide the server."""
import asyncio
import os
import uuid
from contextvars import copy_context
from enum import Enum
from os import environ as env
from typing import Any, Dict, List, Optional, Union

import socketio
import uvicorn
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from pydantic import BaseModel, EmailStr  # pylint: disable=no-name-in-module

from imjoy import __version__ as VERSION
from imjoy.core.auth import JWT_SECRET, get_user_info, valid_token
from imjoy.core.connection import BasicConnection
from imjoy.core.plugin import DynamicPlugin
from imjoy.core.interface import CoreInterface, current_user

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)


class VisibilityEnum(str, Enum):
    """Represent the visibility of the workspace."""

    public = "public"
    protected = "protected"


class UserInfo(BaseModel):
    """Represent user info."""

    sessions: List[str]
    id: str
    roles: List[str]
    email: Optional[EmailStr]
    parent: Optional[str]
    scopes: Optional[List[str]]  # a list of workspace
    expires_at: Optional[int]
    plugins: Optional[Dict[str, Any]]  # id:plugin


sessions: Dict[str, UserInfo] = {}  # sid:user_info
users: Dict[str, UserInfo] = {}  # uid:user_info
all_plugins: Dict[str, Dict[str, Any]] = {}  # workspace: {name: plugin}


def parse_token(authorization):
    """Parse the token."""
    if not authorization.startswith("imjoy@"):
        # auth0 token
        return get_user_info(valid_token(authorization))

    parts = authorization.split()
    if parts[0].lower() != "bearer":
        raise Exception("Authorization header must start with" " Bearer")
    if len(parts) == 1:
        raise Exception("Token not found")
    if len(parts) > 2:
        raise Exception("Authorization header must be 'Bearer' token")

    token = parts[1]
    # generated token
    token = token.lstrip("imjoy@")
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


def check_permission(workspace, user_info):
    """Check permission."""
    if workspace == user_info.id:
        return True
    return False


def initialize_socketio(sio, core_api):
    """Initialize socketio."""
    # pylint: disable=too-many-statements, unused-variable

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
                scopes = user_info.get("scopes")
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

        if uid not in users:
            users[uid] = UserInfo(
                sessions=[sid],
                id=uid,
                email=email,
                parent=parent,
                roles=roles,
                scopes=scopes,
                expires_at=expires_at,
            )
        else:
            users[uid].sessions.append(sid)
        sessions[sid] = users[uid]

    @sio.event
    async def register_plugin(sid, config):
        user_info = sessions[sid]
        workspace = config.get("workspace") or user_info.id
        config["workspace"] = workspace
        # if not check_permission(workspace, user_info):
        #     return {
        #         "success": False, "detail": "
        #         "f"Permission denied for workspace: {workspace}"
        #     }

        name = config["name"].replace("/", "-")  # prevent hacking of the plugin name
        plugin_id = f"{workspace}/{name}"
        config["id"] = plugin_id
        sio.enter_room(sid, plugin_id)

        async def send(data):
            await sio.emit(
                "plugin_message", data, room=plugin_id,
            )

        connection = BasicConnection(send)
        plugin = DynamicPlugin(config, core_api.get_interface(), connection)
        if user_info.plugins:
            user_info.plugins[plugin.id] = plugin
        else:
            user_info.plugins = {plugin.id: plugin}

        if workspace in all_plugins:
            ws_plugins = all_plugins[workspace]
        else:
            ws_plugins = {}
            all_plugins[workspace] = ws_plugins
        if plugin.name in ws_plugins:
            # kill the plugin if already exist
            asyncio.ensure_future(plugin.terminate(True))
            del user_info.plugins[plugin.id]
        ws_plugins[plugin.name] = plugin
        logger.info("New plugin registered successfully (%s)", plugin_id)
        return {"success": True, "plugin_id": plugin_id}

    @sio.event
    async def plugin_message(sid, data):
        user_info = sessions[sid]
        data["context"] = {"user_info": user_info}
        plugin_id = data["plugin_id"]
        workspace, name = os.path.split(plugin_id)
        # if not check_permission(workspace, user_info):
        #     logger.error(
        #         "Permission denied: workspace=%s, user_id=%s", workspace, user_info.id
        #     )
        #     return {"success": False, "detail": "Permission denied"}
        if all_plugins[workspace]:
            plugin = all_plugins[workspace].get(name)
            if plugin:
                current_user.set(user_info)
                ctx = copy_context()
                ctx.run(plugin.connection.handle_message, data)
                return {"success": True}
        logger.warning("Unhandled message for plugin %s", plugin_id)
        return {"success": False, "detail": "Plugin not found"}

    @sio.event
    async def disconnect(sid):
        """Event handler called when the client is disconnected."""
        user_info = sessions[sid]
        users[user_info.id].sessions.remove(sid)
        # if the user has no more sessions
        if not users[user_info.id].sessions:
            del users[user_info.id]
            if user_info.plugins:
                for plugin_name in list(user_info.plugins):
                    plugin = user_info.plugins[plugin_name]
                    # TODO: how to allow plugin running when the user disconnected
                    # we will also need to handle the case when the user login again
                    # the plugin should be reclaimed for the user
                    asyncio.ensure_future(plugin.terminate())
                    del user_info.plugins[plugin_name]
                    del all_plugins[plugin.workspace][plugin.name]
                    if not all_plugins[plugin.workspace]:
                        del all_plugins[plugin.workspace]
                    core_api.remove_plugin_services(plugin)
        del sessions[sid]


def create_application(allow_origins) -> FastAPI:
    """Set up the server application."""
    # pylint: disable=unused-variable

    app = FastAPI(
        title="ImJoy Core Server",
        description=(
            "A server for managing imjoy plugins and enabling remote procedure calls"
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

    @app.get("/")
    async def root():
        return {
            "name": "ImJoy Core Server",
            "version": VERSION,
            "users": {u: users[u].sessions for u in users},
            "all_plugins": {k: list(all_plugins[k].keys()) for k in all_plugins},
        }

    return app


def setup_socketio_server(
    app: FastAPI,
    mount_location: str = "/",
    socketio_path: str = "socket.io",
    allow_origins: Union[str, list] = "*",
) -> None:
    """Set up the socketio server."""
    if allow_origins == ["*"]:
        allow_origins = "*"
    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=allow_origins)
    _app = socketio.ASGIApp(socketio_server=sio, socketio_path=socketio_path)

    app.mount(mount_location, _app)
    app.sio = sio
    core_api = CoreInterface(plugins=all_plugins)
    initialize_socketio(sio, core_api)
    return sio


def start_server(args):
    """Start the socketio server."""
    if args.allow_origin:
        allow_origin = args.allow_origin.split(",")
    else:
        allow_origin = env.get("ALLOW_ORIGINS", "*").split(",")
    application = create_application(allow_origin)
    setup_socketio_server(application, allow_origins=allow_origin)
    uvicorn.run(application, host=args.host, port=int(args.port))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="host for the socketio server",
    )
    parser.add_argument(
        "--port", type=int, default=3000, help="port for the socketio server",
    )
    parser.add_argument(
        "--allow-origin", type=str, default="*", help="origins for the socketio server",
    )
    opt = parser.parse_args()
    start_server(opt)
