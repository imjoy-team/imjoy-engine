"""Provide utils for Python 2 plugins."""
import copy
import threading
import time
import uuid


def debounce(s):
    """Decorate to ensure function can only be called once every `s` seconds."""

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
    """Set interval."""

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
    """Access dictionary attributes with dot.notation."""

    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __deepcopy__(self, memo=None):
        """Make a deep copy."""
        return dotdict(copy.deepcopy(dict(self), memo=memo))


def getKeyByValue(d, value):
    """Return key by value."""
    for k, v in d.items():
        if value == v:
            return k
    return None


def formatTraceback(traceback_string):
    formatted_lines = traceback_string.splitlines()
    # remove the second and third line
    formatted_lines.pop(1)
    formatted_lines.pop(1)
    formatted_error_string = "\n".join(formatted_lines)
    formatted_error_string = formatted_error_string.replace(
        'File "<string>"', "Plugin script"
    )
    return formatted_error_string


class ReferenceStore:
    """Represent a reference store."""

    def __init__(self):
        """Set up store."""
        self._store = {}

    def _genId(self):
        """Generate an id."""
        return str(uuid.uuid4())

    def put(self, obj):
        """Put an object into the store."""
        id = self._genId()
        self._store[id] = obj
        return id

    def fetch(self, id):
        """Fetch an object from the store by id."""
        if id not in self._store:
            return None
        obj = self._store[id]
        if not hasattr(obj, "__remote_method"):
            del self._store[id]
        if hasattr(obj, "__jailed_pairs__"):
            _id = getKeyByValue(self._store, obj.__jailed_pairs__)
            self.fetch(_id)
        return obj


class Promise(object):
    """Represent a promise."""

    def __init__(self, pfunc):
        """Set up promise."""
        self._resolve_handler = None
        self._finally_handler = None
        self._catch_handler = None

        def resolve(*args, **kwargs):
            self.resolve(*args, **kwargs)

        def reject(*args, **kwargs):
            self.reject(*args, **kwargs)

        pfunc(resolve, reject)

    def resolve(self, result):
        """Resolve promise."""
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
        """Reject promise."""
        try:
            if self._catch_handler:
                self._catch_handler(error)
            elif not self._finally_handler:
                print("Uncaught Exception: " + str(error))
        finally:
            if self._finally_handler:
                self._finally_handler()

    def then(self, handler):
        """Implement then callback.

        Set handler and return the promise.
        """
        self._resolve_handler = handler
        return self

    def finally_(self, handler):
        """Implement finally callback.

        Set handler and return the promise.
        """
        self._finally_handler = handler
        return self

    def catch(self, handler):
        """Implement catch callback.

        Set handler and return the promise.
        """
        self._catch_handler = handler
        return self
