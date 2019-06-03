"""Provide a mock plugin."""
import asyncio
import logging
import sys

import janus
import numpy as np

from imjoy.utils import dotdict
from imjoy.workers.python_worker import PluginConnection
from imjoy.workers.python3_client import JOB_HANDLERS_PY3

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO)

NAME_SPACE = "/"


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


class TestPlugin:
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
            self.message_handler(msg)

    def get_api(self):
        """return the plugin api functions."""
        return self.conn.local["api"]

    async def message_worker(self, async_q, abort=None):
        """Implement a message worker."""
        while True:
            try:
                if abort is not None and abort.is_set():
                    break

                job = await async_q.get()
                async_q.task_done()
                if job is None:
                    continue

                if "setInterface" == job["type"]:
                    api = self.conn.set_remote(job["api"])
                    self.conn.local["np"] = np
                    self.conn.emit({"type": "interfaceSetAsRemote"})
                    if not self.conn.init:
                        self.conn.set_interface(self.imjoy_api)
                        self.conn.init = True
                    async_q.task_done()
                else:
                    handler = JOB_HANDLERS_PY3.get(job["type"])
                    if handler is None:
                        continue
                    try:
                        await handler(self.conn, job, logger)
                    except Exception:  # pylint: disable=broad-except
                        logger.error(
                            "Error occured in the loop %s", traceback.format_exc()
                        )
                    finally:
                        sys.stdout.flush()
            except Exception as e:
                print(e)

    def terminate(self, msg):
        """mark the plugin as terminated."""
        logger.info("Plugin disconnected: %s", msg)
        self.terminated = True

    async def init(self):
        """initialize the plugin."""
        opt = dotdict(id=self.pid, secret=self.secret)
        self.conn = PluginConnection(opt, client=self)
        self.terminated = False
        initialized = self.loop.create_future()
        self.on_plugin_message("initialized", initialized)
        self.on_plugin_message("disconnected", self.terminate)
        await initialized

        workers = [
            self.message_worker(self.janus_queue.async_q, self.conn.abort)
            for i in range(2)
        ]
        asyncio.ensure_future(asyncio.gather(*workers))

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

    def message_handler(self, msg):
        """Handle plugin message."""
        msg_type = msg["type"]
        handlers = self._plugin_message_handler
        for h in handlers:
            # extract message
            if msg_type == "message":
                job = msg["data"]
                self.queue.put(job)
                logger.debug("Added task to the queue")

            elif msg_type == h["type"]:
                callback_or_future = h["callback_or_future"]
                if isinstance(callback_or_future, asyncio.Future):
                    callback_or_future.set_result(msg)
                else:
                    callback_or_future(msg)
