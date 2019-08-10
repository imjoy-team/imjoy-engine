"""Provide worker functions for Python 3."""
import asyncio
import logging
import sys
import traceback

import janus

from .utils import format_traceback
from .python3_client import AsyncClient, task_worker, JOB_HANDLERS

from ipykernel.comm import Comm

import os

# pylint: disable=unused-argument, redefined-outer-name

logger = logging.getLogger("jupyter_client")


class JupyterClient(AsyncClient):
    """Represent an async socketio client."""

    # pylint: disable=too-few-public-methods
    def __init__(self, conn, opt):
        """Set up client instance."""
        self.conn = conn
        self.opt = opt
        self.comm = None
        self.loop = asyncio.get_event_loop()
        self.janus_queue = janus.Queue(loop=self.loop)
        self.queue = self.janus_queue.sync_q
        self.task_worker = task_worker

    def setup(self):
        """Set up the plugin connection."""
        logger.setLevel(logging.INFO)
        if self.opt.debug:
            logger.setLevel(logging.DEBUG)
        self.comm = Comm(target_name="imjoy_comm_target", data={})
        self.comm.open()
        self.comm.on_msg(self.comm_plugin_message)

        def on_disconnect():
            if not self.opt.daemon:
                self.conn.exit(1)

        self.comm.on_close(on_disconnect)
        sys.stdout.flush()

    def connect(self):
        """Connect to the socketio server."""
        self.emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", self.opt.id)

    def emit(self, msg):
        """Emit a message to the socketio server."""
        logger.info("========> sending msg: %s", msg)
        self.comm.send(msg)

    def comm_plugin_message(self, msg):
        """Handle plugin message."""
        data = msg["content"]["data"]
        logger.info("=========> processing message %s", data)

        # if not self.conn.executed:
        #    self.emit({'type': 'message', 'data': {"type": "interfaceSetAsRemote"}})

        if data["type"] == "import":
            self.emit({"type": "importSuccess", "url": data["url"]})
        elif data["type"] == "disconnect":
            self.conn.abort.set()
            try:
                if "exit" in self.conn.interface and callable(
                    self.conn.interface["exit"]
                ):
                    self.conn.interface["exit"]()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error when exiting: %s", exc)
            return None
        elif data["type"] == "execute":
            if not self.conn.executed:
                handler = JOB_HANDLERS.get(data["type"])
                if not handler:
                    self.emit({"type": "nohanler-" + data["type"]})
                    return
                handler(self.conn, data, logger)
            else:
                logger.debug("Skip execution")
                self.emit({"type": "executeSuccess"})
        elif data["type"] == "message":
            _data = data["data"]
            handler = JOB_HANDLERS.get(_data["type"])
            if not handler:
                self.emit({"type": "nohanler=" + _data["type"], "msg": _data})
                return
            handler(self.conn, _data, logger)
            self.emit({"type": "log", "msg=": _data})
            logger.debug("Added task to the queue")
        sys.stdout.flush()
        return None
