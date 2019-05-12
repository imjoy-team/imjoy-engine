"""Provide utils for Python 3 plugins."""
import asyncio
import sys
import traceback

from imjoyUtils import Promise

from .worker import JOB_HANDLERS_PY3


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


class FuturePromise(Promise, asyncio.Future):
    """Represent a promise as a future."""

    def __init__(self, pfunc, loop):
        """Set up promise."""
        self.loop = loop
        Promise.__init__(self, pfunc)
        asyncio.Future.__init__(self)

    def resolve(self, result):
        """Resolve promise."""
        if self._resolve_handler or self._finally_handler:
            super().resolve(self, result)
        else:
            self.loop.call_soon(self.set_result, result)

    def reject(self, error):
        """Reject promise."""
        if self._catch_handler or self._finally_handler:
            super().reject(self, error)
        else:
            if error:
                self.loop.call_soon(self.set_exception, Exception())
            else:
                self.loop.call_soon(self.set_exception, Exception(str(error)))
