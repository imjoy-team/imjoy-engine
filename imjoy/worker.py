"""Provide worker functions."""
import traceback
import sys
import time

from imjoyUtils import formatTraceback
from util import Registry

try:
    import queue
except ImportError:
    import Queue as queue

# pylint: disable=unused-argument

JOB_HANDLERS = Registry()


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
        handler(conn, job, logger)
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
            logger.error("error during execution: %s", traceback_error)
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
                logger.error("error in method %s: %s", job["name"], traceback_error)
                reject(Exception(formatTraceback(traceback_error)))
        else:
            try:
                method = interface[job["name"]]
                args = conn.unwrap(job["args"], True)
                # args.append({'id': conn.id})
                method(*args)
            except Exception:  # pylint: disable=broad-except
                logger.error(
                    "error in method %s: %s", job["name"], traceback.format_exc()
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
            logger.error("error in method %s: %s", job["num"], traceback_error)
            reject(Exception(formatTraceback(traceback_error)))
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
            logger.error("error in method %s: %s", job["num"], traceback.format_exc())
