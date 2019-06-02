"""Provide a mock client."""
import asyncio
import logging
import sys
import uuid
from pathlib import Path

import janus
import socketio

from imjoy.helper import dotdict
from imjoy.workers.worker_template import PluginConnection
from imjoy.workers.worker3 import JOB_HANDLERS_PY3

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO)

NAME_SPACE = "/"


async def task_worker(conn, async_q, logger, abort=None):
    """Implement a task worker."""
    while True:
        try:
            if abort is not None and abort.is_set():
                break
            job = await async_q.get()
            if job is None:
                async_q.task_done()
                continue

            if "setInterface" == job["type"]:
                api = conn.set_remote(job["api"])
                conn.emit({"type": "interfaceSetAsRemote"})
                if not conn.init:
                    conn.init = True
            else:
                handler = JOB_HANDLERS_PY3.get(job["type"])
                if handler is None:
                    async_q.task_done()
                    continue
                try:
                    await handler(conn, job, logger)
                except Exception:  # pylint: disable=broad-except
                    logger.error("Error occured in the loop %s", traceback.format_exc())
                finally:
                    sys.stdout.flush()
                    async_q.task_done()

        except Exception as e:
            print(e)


class ImJoyAPI:
    """ Represent a set of mock ImJoy API """

    def log(self, message):
        logger.info("log: %s", message)

    def error(self, message):
        logger.info("error: %s", message)

    def alert(self, message):
        logger.info("alert: %s", message)

    def showStatus(self, message):
        logger.info("showStatus: %s", message)

    def showMessage(self, message):
        logger.info("showMessage: %s", message)


class Plugin:
    """ Represent a mock proxy plugin """

    def __init__(self, loop, sio, pid, secret):
        self.conn = None
        self.loop = loop
        self.sio = sio
        self.pid = pid
        self.secret = secret
        self._plugin_message_handler = []
        self.api = None
        self.imjoy_api = ImJoyAPI()
        self.janus_queue = janus.Queue(loop=self.loop)
        self.queue = self.janus_queue.sync_q

        @sio.on("message_from_plugin_" + secret)
        async def on_message(msg):  # pylint:disable=unused-variable
            logger.info("Message from plugin: %s", msg)
            await self.message_handler(msg)

    def get_api(self):
        return self.conn.local["api"]

    async def init(self):
        opt = dotdict(id=self.pid, secret=self.secret)
        self.conn = PluginConnection(opt, client=self)
        initialized = self.loop.create_future()
        self.on_plugin_message("initialized", initialized)
        await initialized
        self.conn.set_interface(self.imjoy_api)
        interfaceSet = self.loop.create_future()
        self.on_plugin_message("interfaceSetAsRemote", interfaceSet)
        self.conn.send_interface()

        workers = [
            task_worker(self.conn, self.janus_queue.async_q, logger, self.conn.abort)
            for i in range(10)
        ]
        asyncio.ensure_future(asyncio.gather(*workers))
        # await interfaceSet

    async def _emit(self, channel, data):
        """Emit a message."""
        fut = self.loop.create_future()

        def callback(ret=None):
            fut.set_result(ret)

        await self.sio.emit(channel, data, namespace=NAME_SPACE, callback=callback)
        return await fut

    async def emit_plugin_message(self, data):
        """Emit plugin message."""
        await self._emit(
            "message_to_plugin_" + self.secret, {"type": "message", "data": data}
        )

    def emit(self, data):
        """Emit plugin message."""
        asyncio.ensure_future(
            self.emit_plugin_message({"type": "message", "data": data})
        )

    def on_plugin_message(self, message_type, callback_or_future):
        """Add a new plugin message."""
        self._plugin_message_handler.append(
            {"type": message_type, "callback_or_future": callback_or_future}
        )

    async def execute(self, code):
        """Execute plugin code."""
        future = self.loop.create_future()

        def resolve(ret):
            future.set_result(ret)

        def reject(_):
            future.set_exception(Exception("executeFailure"))

        self.on_plugin_message("executeSuccess", resolve)
        self.on_plugin_message("executeFailure", reject)
        await self.emit_plugin_message({"type": "execute", "code": code})
        result = await future
        assert result == {"type": "executeSuccess"}
        await self.emit_plugin_message({"type": "getInterface"})

    async def message_handler(self, msg):
        """Handle plugin message."""
        msg_type = msg["type"]
        handlers = self._plugin_message_handler
        for h in handlers:
            # extract message
            if msg_type == "message":
                job = msg["data"]
                self.queue.put(job)
                logger.debug("Added task to the queue")

            if msg_type == h["type"]:
                callback_or_future = h["callback_or_future"]
                if isinstance(callback_or_future, asyncio.Future):
                    callback_or_future.set_result(msg)
                else:
                    callback_or_future(msg)


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

        await self.sio.emit(channel, data, namespace=NAME_SPACE, callback=callback)
        return await fut

    async def init_plugin(self, plugin_config):
        """Initialize the plugin."""
        pid = plugin_config["name"] + "_" + str(uuid.uuid4())
        ret = await self.emit("init_plugin", {"id": pid, "config": plugin_config})
        assert ret["success"] is True
        secret = ret["secret"]
        plugin = Plugin(self.loop, self.sio, pid, secret)
        await plugin.init()
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
