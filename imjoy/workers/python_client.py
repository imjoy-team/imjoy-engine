"""Provide worker functions."""
import logging
import traceback
import sys
import time

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

    def __init__(self, conn, opt):
        """Set up client instance."""
        self.conn = conn
        self.opt = opt
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
        sys.stdout.flush()

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
                self.queue.put(data)
            else:
                logger.debug("Skip execution")
                self.emit({"type": "executeSuccess"})
        elif data["type"] == "message":
            _data = data["data"]
            self.queue.put(_data)
            logger.debug("Added task to the queue")
        sys.stdout.flush()
        return None

    def run_forever(self):
        """Run forever."""
        raise NotImplementedError


class Client(BaseClient):
    """Represent a sync socketio client."""

    def __init__(self, conn, opt):
        """Set up client instance."""
        super(Client, self).__init__(conn, opt)
        self.queue = queue.Queue()

    def run_forever(self):
        """Run forever."""
        task_worker(self.conn, self.queue, logger, self.conn.abort)
