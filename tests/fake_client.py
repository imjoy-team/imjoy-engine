import os
import sys
import asyncio
import socketio
import logging

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("fake_client")

class FakeClient:
    def __init__(self, url, client_id, session_id, token, loop=None):
        self.engine_info = None
        self.url = url
        self.client_id = client_id
        self.session_id = session_id
        self.token = token
        if loop is None:
            self.loop = asyncio.get_event_loop()
        else:
            self.loop = loop
    
    async def emit(self, channel, data):
        fut = self.loop.create_future()
        def callback(ret):
            fut.set_result(ret)
        await self.sio.emit(channel, data, namespace=NAME_SPACE, callback=callback)
        return await fut

    async def connect(self):
        sio = socketio.AsyncClient()
        self.sio = sio
        fut = self.loop.create_future()

        @sio.on("connect")
        async def on_connect():
            fut.set_result(True)

        @sio.on("disconnect")
        async def on_disconnect():
            fut.set_exception(Exception('client disconnected'))
    
        await sio.connect(self.url)
        return await fut

    async def register_client(self):
        ret = await self.emit(
            "register_client",
            {
                "id": self.client_id,
                "token": self.token,
                "base_url": self.url,
                "session_id": self.session_id,
            }
        )
        if "success" in ret and ret["success"]:
            self.engine_info = ret["engine_info"]
        else:
            logger.error("Failed to register")

    async def init_plugin(self, plugin_config):
        ret = await self.emit(
            "init_plugin",
            {"id": "test_plugin", "config": plugin_config},
        )
        assert ret["success"] == True
        secret = ret["secret"]
        work_dir = ret["work_dir"]
        resumed = ret.get("resumed")

        initialized = self.loop.create_future()

        @self.sio.on("message_from_plugin_" + secret)
        async def on_message(msg):
            logger.info("message from plugin: %s", msg)
            msg_type = msg["type"]
            if msg_type == "initialized":
                initialized.set_result(True)
        return await initialized

    async def run(self, plugin_config):
        await self.connect()
        await self.register_client()
        await self.init_plugin(plugin_config)
        


if __name__ == '__main__':
    import uuid

    WORKSPACE_DIR = os.path.expanduser("~/ImJoyWorkspace")
    NAME_SPACE = "/"
    URL = "http://localhost:9527"

    with open(os.path.join(WORKSPACE_DIR, ".token"), "r") as f:
        token = f.read()

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
    client = FakeClient(URL, client_id, session_id, token, loop)
    loop.run_until_complete(client.run(test_plugin_config))