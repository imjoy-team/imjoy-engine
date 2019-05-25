import os
import asyncio
import uuid
import socketio

WORKSPACE_DIR = os.path.expanduser("~/ImJoyWorkspace")
# read token from file if exists
with open(os.path.join(WORKSPACE_DIR, ".token"), "r") as f:
    token = f.read()

client_id = str(uuid.uuid4())
session_id = str(uuid.uuid4())
url = "http://localhost:9527"

NAME_SPACE = "/"

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


class FakeClient:
    def __init__(self, url, client_id, session_id, token):
        self.engine_info = None
        self.url = url
        self.client_id = client_id
        self.session_id = session_id
        self.token = token

    async def init(self):
        sio = socketio.AsyncClient()
        self.sio = sio

        @sio.on("connect")
        async def on_connect():
            print("I'm connected!")
            await self.sio.emit(
                "register_client",
                {
                    "id": self.client_id,
                    "token": self.token,
                    "base_url": self.url,
                    "session_id": self.session_id,
                },
                namespace=NAME_SPACE,
                callback=self.on_registered,
            )

        @sio.on("message")
        async def on_message(data):
            print("I received a message!")

        @sio.on("my message")
        async def on_message(data):
            print("I received a custom message!")

        @sio.on("disconnect")
        async def on_disconnect():
            print("I'm disconnected!")

        await sio.connect(self.url)
        await asyncio.sleep(30)

    async def message_handler(self, msg):
        msg_type = msg["type"]
        if msg_type == "initialized":
            await self.init_site()

    async def init_site(self):
        print("init site.")

    async def on_initialized_plugin(self, ret):
        assert ret["success"] == True
        secret = ret["secret"]
        work_dir = ret["work_dir"]
        resumed = ret.get("resumed")

        @self.sio.on("message_from_plugin_" + secret)
        async def on_message(msg):
            print("message from plugin: ", msg)
            await self.message_handler(msg)

    async def on_registered(self, ret):
        print("registered...")
        if "success" in ret and ret["success"]:
            self.engine_info = ret["engine_info"]

            await self.sio.emit(
                "init_plugin",
                {"id": "test_plugin", "config": test_plugin_config},
                namespace=NAME_SPACE,
                callback=self.on_initialized_plugin,
            )

            print(self.engine_info)
        else:
            print("failed to register")

    def run(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.init())


if __name__ == "__main__":
    client = FakeClient(url, client_id, session_id, token)
    client.run()
