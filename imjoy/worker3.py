"""Provide worker functions for Python 3."""
import asyncio
import inspect
import logging
import sys
import threading
import traceback

import janus
import socketio

from worker_utils import format_traceback
from worker_utils3 import make_coro
from util import Registry
from worker import JOB_HANDLERS

# pylint: disable=unused-argument, redefined-outer-name

logger = logging.getLogger("worker3")

JOB_HANDLERS_PY3 = Registry()
JOB_HANDLERS_PY3.update({name: make_coro(func) for name, func in JOB_HANDLERS.items()})


async def task_worker(conn, async_q, logger, abort=None):
    """Implement a task worker."""
    while True:
        if abort is not None and abort.is_set():
            break
        job = await async_q.get()
        if job is None:
            continue
        handler = JOB_HANDLERS_PY3.get(job["type"])
        if handler is None:
            continue
        try:
            await handler(conn, job, logger)
        except Exception:  # pylint: disable=broad-except
            logger.error("Error occured in the loop %s", traceback.format_exc())
        finally:
            sys.stdout.flush()
            async_q.task_done()


@JOB_HANDLERS_PY3.register("method")
async def handle_method_py3(conn, job, logger):
    """Handle method."""
    if job["name"] in conn.interface:
        if "promise" in job:
            try:
                resolve, reject = conn.unwrap(job["promise"], False)
                method = conn.interface[job["name"]]
                args = conn.unwrap(job["args"], True)
                # args.append({'id': conn.id})
                result = method(*args)
                if result is not None and inspect.isawaitable(result):
                    result = await result
                resolve(result)
            except Exception:  # pylint: disable=broad-except
                traceback_error = traceback.format_exc()
                logger.error("Error in method %s: %s", job["name"], traceback_error)
                reject(Exception(format_traceback(traceback_error)))
        else:
            try:
                method = conn.interface[job["name"]]
                args = conn.unwrap(job["args"], True)
                # args.append({'id': conn.id})
                result = method(*args)
                if result is not None and inspect.isawaitable(result):
                    await result
            except Exception:  # pylint: disable=broad-except
                logger.error(
                    "Error in method %s: %s", job["name"], traceback.format_exc()
                )
    else:
        raise Exception("method " + job["name"] + " is not found.")


@JOB_HANDLERS_PY3.register("callback")
async def handle_callback_py3(conn, job, logger):
    """Handle callback."""
    if "promise" in job:
        resolve, reject = conn.unwrap(job["promise"], False)
        try:
            method = conn.store.fetch(job["num"])
            if method is None:
                raise Exception(
                    "Callback function can only called once, "
                    "if you want to call a function for multiple times, "
                    "please make it as a plugin api function. "
                    "See https://imjoy.io/docs for more details."
                )
            args = conn.unwrap(job["args"], True)
            result = method(*args)
            if result is not None and inspect.isawaitable(result):
                result = await result
            resolve(result)
        except Exception:  # pylint: disable=broad-except
            traceback_error = traceback.format_exc()
            logger.error("Error in method %s: %s", job["num"], traceback_error)
            reject(Exception(format_traceback(traceback_error)))
    else:
        try:
            method = conn.store.fetch(job["num"])
            if method is None:
                raise Exception(
                    "Callback function can only called once, "
                    "if you want to call a function for multiple times, "
                    "please make it as a plugin api function. "
                    "See https://imjoy.io/docs for more details."
                )
            args = conn.unwrap(job["args"], True)
            result = method(*args)
            if result is not None and inspect.isawaitable(result):
                await result
        except Exception:  # pylint: disable=broad-except
            logger.error("Error in method %s: %s", job["num"], traceback.format_exc())


class AsyncClient:
    """Represent an async socketio client."""

    def __init__(self, conn, opt):
        """Set up client instance."""
        self.conn = conn
        self.loop = asyncio.get_event_loop()
        self.opt = opt
        self.queue = janus.Queue(loop=self.loop)
        self.sio = socketio.Client()

    def setup(self):
        """Set up the plugin connection."""
        logger.setLevel(logging.INFO)
        if self.opt.debug:
            logger.setLevel(logging.DEBUG)
        self.sio.on("to_plugin_" + self.opt.secret, self.sio_plugin_message)

        def on_disconnect():
            if not self.opt.daemon:
                self.conn.exit(1)

        self.sio.on("disconnect", on_disconnect)

    def connect(self):
        """Connect to the socketio server."""
        self.sio.connect(self.opt.server)
        self.emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", self.opt.id)

    def emit(self, msg):
        """Emit a message to the socketio server."""
        self.sio.emit("from_plugin_" + self.opt.secret, msg)

    def sio_plugin_message(self, *args):
        """Handle plugin message."""
        data = args[0]
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
            return args
        elif data["type"] == "execute":
            if not self.conn.executed:
                self.queue.sync_q.put(data)
            else:
                logger.debug("Skip execution")
                self.emit({"type": "executeSuccess"})
        elif data["type"] == "message":
            _data = data["data"]
            self.queue.sync_q.put(_data)
            logger.debug("Added task to the queue")
        sys.stdout.flush()
        return None

    def run_forever(self):
        """Wait forever."""
        thread = threading.Thread(target=self.sio.wait)
        thread.daemon = True
        thread.start()
        self.loop.run_until_complete(
            task_worker(self.conn, self.queue.async_q, logger, self.conn.abort)
        )
