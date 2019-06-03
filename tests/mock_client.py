"""Provide a mock client."""
import asyncio
import logging
import sys
import uuid
from pathlib import Path

import socketio

from tests.mock_plugin import TestPlugin

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO)


class TestClient:
    """Represent a mock client."""

    def __init__(self, url, client_id, session_id, token, loop=None):
        """Set up client instance."""
        self.engine_info = None
        self.sio = None
        self.url = url
        self.client_id = client_id
        self.session_id = session_id
        self.token = token
        self.loop = loop or asyncio.get_event_loop()
        self.plugins = []

    def __repr__(self):
        """Return the client representation."""
        return (
            "<TestClient("
            f"url={self.url}, client_id={self.client_id}, "
            f"session_id={self.session_id}, token={self.token})>"
        )

    async def emit(self, channel, data):
        """Emit a message."""
        fut = self.loop.create_future()

        def callback(ret=None):
            fut.set_result(ret)

        await self.sio.emit(channel, data, callback=callback)
        return await fut

    async def init_plugin(self, plugin_config):
        """Initialize the plugin."""
        pid = plugin_config["name"] + "_" + str(uuid.uuid4())
        ret = await self.emit("init_plugin", {"id": pid, "config": plugin_config})
        assert ret["success"] is True
        secret = ret["secret"]
        plugin = TestPlugin(self.loop, self.sio, pid, secret)
        await plugin.init()
        self.plugins.append(plugin)
        return plugin

    async def connect(self):
        """Connect to the server."""
        sio = socketio.AsyncClient()
        self.sio = sio
        fut = self.loop.create_future()

        @sio.on("connect")
        async def on_connect():  # pylint:disable=unused-variable
            fut.set_result(True)

        @sio.on("disconnect")
        async def on_disconnect():  # pylint:disable=unused-variable
            print("Client disconnected.")
            for plugin in self.plugins:
                plugin.conn.abort.set()

        await sio.connect(self.url)
        return await fut

    async def register_client(self):
        """Register the client."""
        ret = await self.emit(
            "register_client",
            {
                "id": self.client_id,
                "token": self.token,
                "base_url": self.url,
                "session_id": self.session_id,
            },
        )
        if "success" in ret and ret["success"]:
            self.engine_info = ret["engine_info"]
        else:
            logger.error("Failed to register")
            raise Exception("Failed to register")


def main():
    """Run main."""
    home = Path.home()
    workspace_dir = home / "ImJoyWorkspace"
    token_file = workspace_dir / ".token"
    token = token_file.read_text()

    url = "http://localhost:9527"

    client_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    test_plugin_config = {
        "name": "test-plugin",
        "type": "native-python",
        "version": "0.1.12",
        "api_version": "0.1.2",
        "description": "This is a test plugin.",
        "tags": ["CPU", "GPU", "macOS CPU"],
        "ui": "",
        "inputs": None,
        "outputs": None,
        "flags": [],
        "icon": None,
        "env": "conda create -n test-env python=3.6.7",
        "requirements": "pip: numpy",
        "dependencies": [],
    }
    loop = asyncio.get_event_loop()
    client = TestClient(url, client_id, session_id, token, loop)

    async def run():
        await client.connect()
        await client.register_client()
        plugin = await client.init_plugin(test_plugin_config)

    loop.run_until_complete(run())


if __name__ == "__main__":
    main()
