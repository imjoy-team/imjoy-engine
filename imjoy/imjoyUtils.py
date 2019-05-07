import sys
import traceback
import copy
import uuid

try:
    import queue
except ImportError:
    import Queue as queue


def debounce(s):
    """Decorator ensures function that can only be called once every `s` seconds.
    """

    def decorate(f):
        d = {"t": None}

        def wrapped(*args, **kwargs):
            if d["t"] is None or time.time() - d["t"] >= s:
                result = f(*args, **kwargs)
                d["t"] = time.time()
                return result

        return wrapped

    return decorate


def setInterval(interval):
    def decorator(function):
        def wrapper(*args, **kwargs):
            stopped = threading.Event()

            def loop():  # executed in another thread
                while not stopped.wait(interval):  # until stopped
                    function(*args, **kwargs)

            t = threading.Thread(target=loop)
            t.daemon = True  # stop if the program exits
            t.start()
            return stopped

        return wrapper

    return decorator


class dotdict(dict):
    """dot.notation access to dictionary attributes"""

    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __deepcopy__(self, memo=None):
        return dotdict(copy.deepcopy(dict(self), memo=memo))


def getKeyByValue(d, value):
    for k, v in d.items():
        if value == v:
            return k
    return None


class ReferenceStore:
    def __init__(self):
        self._store = {}

    def _genId(self):
        return str(uuid.uuid4())

    def put(self, obj):
        id = self._genId()
        self._store[id] = obj
        return id

    def fetch(self, id):
        if id not in self._store:
            return None
        obj = self._store[id]
        if not hasattr(obj, "__remote_method"):
            del self._store[id]
        if hasattr(obj, "__jailed_pairs__"):
            _id = getKeyByValue(self._store, obj.__jailed_pairs__)
            self.fetch(_id)
        return obj


def task_worker(self, q, logger, abort):
    while True:
        try:
            if abort is not None and abort.is_set():
                break
            d = q.get()
            q.task_done()
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
                interface = self._interface
                if "pid" in d and d["pid"] is not None:
                    interface = self._plugin_interfaces[d["pid"]]
                if d["name"] in interface:
                    if "promise" in d:
                        try:
                            resolve, reject = self._unwrap(d["promise"], False)
                            method = interface[d["name"]]
                            args = self._unwrap(d["args"], True)
                            # args.append({'id': self.id})
                            result = method(*args)
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
                            method = interface[d["name"]]
                            args = self._unwrap(d["args"], True)
                            # args.append({'id': self.id})
                            method(*args)
                        except Exception as e:
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
                        method(*args)
                    except Exception as e:
                        logger.error(
                            "error in method %s: %s", d["num"], traceback.format_exc()
                        )
            sys.stdout.flush()
        except queue.Empty:
            time.sleep(0.1)


class Promise(object):
    def resolve(self, result):
        try:
            if self._resolve_handler:
                self._resolve_handler(result)
        except Exception as e:
            if self._catch_handler:
                self._catch_handler(e)
            elif not self._finally_handler:
                print("Uncaught Exception: " + str(e))
        finally:
            if self._finally_handler:
                self._finally_handler()

    def reject(self, error):
        try:
            if self._catch_handler:
                self._catch_handler(error)
            elif not self._finally_handler:
                print("Uncaught Exception: " + str(error))
        finally:
            if self._finally_handler:
                self._finally_handler()

    def then(self, handler):
        self._resolve_handler = handler
        return self

    def finally_(self, handler):
        self._finally_handler = handler
        return self

    def catch(self, handler):
        self._catch_handler = handler
        return self

    def __init__(self, pfunc):
        self._resolve_handler = None
        self._finally_handler = None
        self._catch_handler = None

        def resolve(*args, **kwargs):
            self.resolve(*args, **kwargs)

        def reject(*args, **kwargs):
            self.reject(*args, **kwargs)

        pfunc(resolve, reject)
