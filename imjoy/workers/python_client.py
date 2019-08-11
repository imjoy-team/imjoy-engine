"""Provide worker functions."""
import logging
import traceback
import sys
import time
import uuid

import socketio

from .utils import format_traceback, Registry

try:
    import queue
except ImportError:
    import Queue as queue

# pylint: disable=unused-argument, redefined-outer-name

JOB_HANDLERS = Registry()
logger = logging.getLogger("python_client")


def task_worker(conn, sync_q, logger, abort):
    """Implement a task worker."""
    while True:
        if abort is not None and abort.is_set():
            break
        try:
            job = sync_q.get()
        except queue.Empty:
            time.sleep(0.1)
            continue
        sync_q.task_done()
        if job is None:
            continue
        handler = JOB_HANDLERS.get(job["type"])
        if handler is None:
            continue

        try:
            handler(conn, job, logger)
        except Exception:  # pylint: disable=broad-except
            logger.error("Error occured in the loop %s", traceback.format_exc())
        sys.stdout.flush()


@JOB_HANDLERS.register("getInterface")
def handle_get_interface(conn, job, logger):
    """Handle get interface."""
    conn.send_interface()


@JOB_HANDLERS.register("setInterface")
def handle_set_interface(conn, job, logger):
    """Handle set interface."""
    conn.set_remote(job["api"])
    conn.emit({"type": "interfaceSetAsRemote"})
    if not conn.init:
        conn.emit({"type": "getInterface"})
        conn.init = True


@JOB_HANDLERS.register("interfaceSetAsRemote")
def handle_set_interface_as_remote(conn, job, logger):
    """Handle set interface as remote."""
    # conn.emit({'type':'getInterface'})
    conn.remote_set = True


@JOB_HANDLERS.register("execute")
def handle_execute(conn, job, logger):
    """Handle execute."""
    if not conn.executed:
        try:
            type_ = job["code"]["type"]
            if type_ == "script":
                content = job["code"]["content"]
                exec(content, conn.local)  # pylint: disable=exec-used
                conn.executed = True
            elif type_ == "requirements":
                pass
            else:
                raise Exception("unsupported type")
            conn.emit({"type": "executeSuccess"})
        except Exception:  # pylint: disable=broad-except
            traceback_error = traceback.format_exc()
            logger.error("Error during execution: %s", traceback_error)
            conn.emit({"type": "executeFailure", "error": traceback_error})
    else:
        logger.info("Skip code execution")


@JOB_HANDLERS.register("method")
def handle_method(conn, job, logger):
    """Handle method."""
    interface = conn.interface
    if "pid" in job and job["pid"] is not None:
        interface = conn.plugin_interfaces[job["pid"]]
    if job["name"] in interface:
        if "promise" in job:
            try:
                resolve, reject = conn.unwrap(job["promise"], False)
                method = interface[job["name"]]
                args = conn.unwrap(job["args"], True)
                # args.append({'id': conn.id})
                result = method(*args)
                resolve(result)
            except Exception:  # pylint: disable=broad-except
                traceback_error = traceback.format_exc()
                logger.error("Error in method %s: %s", job["name"], traceback_error)
                reject(Exception(format_traceback(traceback_error)))
        else:
            try:
                method = interface[job["name"]]
                args = conn.unwrap(job["args"], True)
                # args.append({'id': conn.id})
                method(*args)
            except Exception:  # pylint: disable=broad-except
                logger.error(
                    "Error in method %s: %s", job["name"], traceback.format_exc()
                )
    else:
        raise Exception("method " + job["name"] + " is not found.")


@JOB_HANDLERS.register("callback")
def handle_callback(conn, job, logger):
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
            method(*args)
        except Exception:  # pylint: disable=broad-except
            logger.error("Error in method %s: %s", job["num"], traceback.format_exc())


class BaseClient(object):  # pylint: disable=useless-object-inheritance
    """Represent a base socketio client."""

    queue = None
    _clients = {}

    @staticmethod
    def get_client(id):
        return BaseClient._clients.get(id)

    def __init__(self, id=None):
        """Set up client instance."""
        self.id = id or str(uuid.uuid4())
        self.sio = socketio.Client()
        BaseClient._clients[self.id] = self

    def setup(self, conn):
        """Set up the plugin connection."""
        self.sio.connect(conn.opt.server)

        def emit(msg):
            """Emit a message to the socketio server."""
            self.sio.emit("from_plugin_" + conn.secret, msg)

        def sio_plugin_message(*args):
            """Handle plugin message."""
            data = args[0]
            if data["type"] == "import":
                emit({"type": "importSuccess", "url": data["url"]})
            elif data["type"] == "disconnect":
                conn.abort.set()
                try:
                    if "exit" in conn.interface and callable(conn.interface["exit"]):
                        conn.interface["exit"]()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Error when exiting: %s", exc)

            elif data["type"] == "execute":
                if not conn.executed:
                    self.queue.put(data)
                else:
                    logger.debug("Skip execution")
                    emit({"type": "executeSuccess"})
            elif data["type"] == "message":
                _data = data["data"]
                self.queue.put(_data)
                logger.debug("Added task to the queue")

        def on_disconnect():
            if not conn.opt.daemon:
                conn.exit(1)

        conn.emit = emit
        self.sio.on("disconnect", on_disconnect)
        self.sio.on("to_plugin_" + conn.secret, sio_plugin_message)
        emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", conn.opt.id)

    def run_forever(self, conn):
        """Run forever."""
        raise NotImplementedError


class Client(BaseClient):
    """Represent a sync socketio client."""

    def __init__(self):
        """Set up client instance."""
        super(Client, self).__init__()
        self.queue = queue.Queue()
        self.task_worker = task_worker

    def run_forever(self, conn):
        """Run forever."""
        self.task_worker(conn, self.queue, logger, conn.abort)
