"""Provide utils for Python 3 plugins."""
import asyncio
import sys
import traceback
import inspect

from imjoyUtils import Promise


async def task_worker(self, async_q, logger, abort=None):
    """Implement a task worker."""
    while True:
        if abort is not None and abort.is_set():
            break
        d = await async_q.get()
        try:
            if d is None:
                continue
            if d["type"] == "getInterface":
                self._sendInterface()
            elif d["type"] == "setInterface":
                self._setRemote(d["api"])
                self.emit({"type": "interfaceSetAsRemote"})
                if not self._init:
                    self.emit({"type": "getInterface"})
                    self._init = True
            elif d["type"] == "interfaceSetAsRemote":
                # self.emit({'type':'getInterface'})
                self._remote_set = True
            elif d["type"] == "execute":
                if not self._executed:
                    try:
                        t = d["code"]["type"]
                        if t == "script":
                            content = d["code"]["content"]
                            exec(content, self._local)
                            self._executed = True
                        elif t == "requirements":
                            pass
                        else:
                            raise Exception("unsupported type")
                        self.emit({"type": "executeSuccess"})
                    except Exception as e:
                        logger.info(
                            "error during execution: %s", traceback.format_exc()
                        )
                        self.emit({"type": "executeFailure", "error": repr(e)})
            elif d["type"] == "method":
                if d["name"] in self._interface:
                    if "promise" in d:
                        try:
                            resolve, reject = self._unwrap(d["promise"], False)
                            method = self._interface[d["name"]]
                            args = self._unwrap(d["args"], True)
                            # args.append({'id': self.id})
                            result = method(*args)
                            if result is not None and inspect.isawaitable(result):
                                result = await result
                            resolve(result)
                        except Exception as e:
                            logger.error(
                                "error in method %s: %s",
                                d["name"],
                                traceback.format_exc(),
                            )
                            reject(e)
                    else:
                        try:
                            method = self._interface[d["name"]]
                            args = self._unwrap(d["args"], True)
                            # args.append({'id': self.id})
                            result = method(*args)
                            if result is not None and inspect.isawaitable(result):
                                await result
                        except Exception:
                            logger.error(
                                "error in method %s: %s",
                                d["name"],
                                traceback.format_exc(),
                            )
                else:
                    raise Exception("method " + d["name"] + " is not found.")
            elif d["type"] == "callback":
                if "promise" in d:
                    resolve, reject = self._unwrap(d["promise"], False)
                    try:
                        method = self._store.fetch(d["num"])
                        if method is None:
                            raise Exception(
                                "Callback function can only called once, "
                                "if you want to call a function for multiple times, "
                                "please make it as a plugin api function. "
                                "See https://imjoy.io/docs for more details."
                            )
                        args = self._unwrap(d["args"], True)
                        result = method(*args)
                        if result is not None and inspect.isawaitable(result):
                            result = await result
                        resolve(result)
                    except Exception as e:
                        logger.error(
                            "error in method %s: %s", d["num"], traceback.format_exc()
                        )
                        reject(e)
                else:
                    try:
                        method = self._store.fetch(d["num"])
                        if method is None:
                            raise Exception(
                                "Callback function can only called once, "
                                "if you want to call a function for multiple times, "
                                "please make it as a plugin api function. "
                                "See https://imjoy.io/docs for more details."
                            )
                        args = self._unwrap(d["args"], True)
                        result = method(*args)
                        if result is not None and inspect.isawaitable(result):
                            await result
                    except Exception:
                        logger.error(
                            "error in method %s: %s", d["num"], traceback.format_exc()
                        )
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
            Promise.resolve(self, result)
        else:
            self.loop.call_soon(self.set_result, result)

    def reject(self, error):
        """Reject promise."""
        if self._catch_handler or self._finally_handler:
            Promise.reject(self, error)
        else:
            if error:
                self.loop.call_soon(self.set_exception, Exception())
            else:
                self.loop.call_soon(self.set_exception, Exception(str(error)))
