"""Provide worker functions for Python 3."""
import inspect
import sys
import traceback

from imjoyUtils import formatTraceback
from imjoyUtils3 import make_coro
from util import Registry
from worker import JOB_HANDLERS

# pylint: disable=unused-argument

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
        except Exception:
            print("error occured in the loop.", traceback.format_exc())
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
                logger.error("error in method %s: %s", job["name"], traceback_error)
                reject(Exception(formatTraceback(traceback_error)))
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
                    "error in method %s: %s", job["name"], traceback.format_exc()
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
            result = method(*args)
            if result is not None and inspect.isawaitable(result):
                await result
        except Exception:  # pylint: disable=broad-except
            logger.error("error in method %s: %s", job["num"], traceback.format_exc())
