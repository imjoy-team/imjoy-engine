"""Provide a worker template."""
import argparse
import inspect
import logging
import math
import os
import sys
import threading
from functools import reduce
from types import ModuleType

from .utils import ReferenceStore, debounce, dotdict, get_psutil, set_interval

if sys.version_info >= (3, 4):
    from .utils3 import FuturePromise
    from .python3_client import AsyncClient

    PYTHON34 = True
else:
    from .utils import Promise
    from .python_client import Client

    PYTHON34 = False

ARRAY_CHUNK = 1000000
logger = logging.getLogger("plugin")


def kill(proc_pid):
    """Kill process id."""
    psutil = get_psutil()
    if psutil is None:
        return

    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()


def ndarray(typed_array, shape, dtype):
    """Return a ndarray."""
    _dtype = type(typed_array)
    if dtype and dtype != _dtype:
        raise Exception(
            "dtype doesn't match the type of the array: " + _dtype + " != " + dtype
        )
    shape = shape or (len(typed_array),)
    return {
        "__jailed_type__": "ndarray",
        "__value__": typed_array,
        "__shape__": shape,
        "__dtype__": _dtype,
    }


API_UTILS = dotdict(
    ndarray=ndarray, kill=kill, debounce=debounce, set_interval=set_interval
)


class PluginConnection:
    """Represent a plugin connection."""

    # pylint:disable=too-many-instance-attributes

    def __init__(self, opt, client=None):
        """Set up connection instance."""
        self.secret = opt.secret
        self.id = opt.id  # pylint: disable=invalid-name
        self.local = {}
        self._remote = dotdict()
        self.interface = {}
        self.plugin_interfaces = {}
        self.remote_set = False
        self.store = ReferenceStore()
        self.executed = False
        self.init = False
        self.abort = threading.Event()
        self.work_dir = opt.work_dir
        self.opt = opt
        if client is not None:
            self.client = client
        elif PYTHON34:
            self.client = AsyncClient(self, self.opt)
        else:
            self.client = Client(self, self.opt)
        self.emit = self.client.emit

    def setup(self):
        """Set up the plugin connection."""
        self.client.setup()
        if not self.work_dir or self.work_dir == ".":
            self.work_dir = os.getcwd()
        else:
            if not os.path.exists(self.work_dir):
                os.makedirs(self.work_dir)
            os.chdir(self.work_dir)

        self._set_local_api(self._remote)

    def start(self):
        """Start the plugin connection."""
        self.client.connect()
        self.client.run_forever()

    def default_exit(self):
        """Exit default."""
        logger.info("Terminating plugin: %s", self.id)
        self.abort.set()
        os._exit(0)  # pylint: disable=protected-access

    def exit(self, code):
        """Exit."""
        if "exit" in self.interface:
            try:
                self.interface["exit"]()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error when exiting: %s", exc)
                sys.exit(1)
            else:
                logger.info("Terminating plugin")
                sys.exit(code)
        else:
            sys.exit(0)

    def _encode(self, a_object):
        """Encode object."""
        if a_object is None:
            return a_object
        if isinstance(a_object, tuple):
            a_object = list(a_object)
        isarray = isinstance(a_object, list)
        b_object = [] if isarray else {}
        # skip if already encoded
        if (
            isinstance(a_object, dict)
            and "__jailed_type__" in a_object
            and "__value__" in a_object
        ):
            return a_object

        # encode interfaces
        if (
            isinstance(a_object, dict)
            and "__id__" in a_object
            and "__jailed_type__" in a_object
            and a_object["__jailed_type__"] == "plugin_api"
        ):
            encoded_interface = {}
            for key, val in a_object.items():
                if callable(val):
                    b_object[key] = {
                        "__jailed_type__": "plugin_interface",
                        "__plugin_id__": a_object["__id__"],
                        "__value__": key,
                        "num": None,
                    }
                    encoded_interface[key] = val
            self.plugin_interfaces[a_object["__id__"]] = encoded_interface
            return b_object

        keys = range(len(a_object)) if isarray else a_object.keys()
        for key in keys:
            val = a_object[key]
            try:
                basestring
            except NameError:
                basestring = str
            if callable(val):
                interface_func_name = None
                for name in self.interface:
                    if self.interface[name] == val:
                        interface_func_name = name
                        break
                if interface_func_name is None:
                    cid = self.store.put(val)
                    v_obj = {
                        "__jailed_type__": "callback",
                        "__value__": "f",
                        "num": cid,
                    }
                else:
                    v_obj = {
                        "__jailed_type__": "interface",
                        "__value__": interface_func_name,
                    }

            # send objects supported by structure clone algorithm
            # https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Structured_clone_algorithm
            # if (
            #   v !== Object(v) ||
            #   v instanceof Boolean ||
            #   v instanceof String ||
            #   v instanceof Date ||
            #   v instanceof RegExp ||
            #   v instanceof Blob ||
            #   v instanceof File ||
            #   v instanceof FileList ||
            #   v instanceof ArrayBuffer ||
            #   v instanceof ArrayBufferView ||
            #   v instanceof ImageData
            # ) {
            # }
            elif "np" in self.local and isinstance(
                val, (self.local["np"].ndarray, self.local["np"].generic)
            ):
                v_byte = val.tobytes()
                if len(v_byte) > ARRAY_CHUNK:
                    v_len = int(math.ceil(1.0 * len(v_byte) / ARRAY_CHUNK))
                    v_bytes = []
                    for i in range(v_len):
                        v_bytes.append(v_byte[i * ARRAY_CHUNK : (i + 1) * ARRAY_CHUNK])
                else:
                    v_bytes = v_byte
                v_obj = {
                    "__jailed_type__": "ndarray",
                    "__value__": v_bytes,
                    "__shape__": val.shape,
                    "__dtype__": str(val.dtype),
                }
            elif isinstance(val, (dict, list)):
                v_obj = self._encode(val)
            elif not isinstance(val, basestring) and isinstance(val, bytes):
                v_obj = val.decode()  # covert python3 bytes to str
            elif isinstance(val, Exception):
                v_obj = {"__jailed_type__": "error", "__value__": str(val)}
            else:
                v_obj = {"__jailed_type__": "argument", "__value__": val}

            if isarray:
                b_object.append(v_obj)
            else:
                b_object[key] = v_obj

        return b_object

    def _decode(self, a_object, callback_id, with_promise):
        """Decode object."""
        if a_object is None:
            return a_object
        if "__jailed_type__" in a_object and "__value__" in a_object:
            if a_object["__jailed_type__"] == "callback":
                b_object = self._gen_remote_callback(
                    callback_id, a_object["num"], with_promise
                )
            elif a_object["__jailed_type__"] == "interface":
                name = a_object["__value__"]
                if name in self._remote:
                    b_object = self._remote[name]
                else:
                    b_object = self._gen_remote_method(name)
            elif a_object["__jailed_type__"] == "plugin_interface":
                b_object = self._gen_remote_method(
                    a_object["__value__"], a_object["__plugin_id__"]
                )
            elif a_object["__jailed_type__"] == "ndarray":
                # create build array/tensor if used in the plugin
                try:
                    np = self.local["np"]  # pylint: disable=invalid-name
                    if isinstance(a_object["__value__"], bytes):
                        a_object["__value__"] = a_object["__value__"]
                    elif isinstance(a_object["__value__"], (list, tuple)):
                        a_object["__value__"] = reduce(
                            (lambda x, y: x + y), a_object["__value__"]
                        )
                    else:
                        raise Exception(
                            "Unsupported data type: ",
                            type(a_object["__value__"]),
                            a_object["__value__"],
                        )
                    b_object = np.frombuffer(
                        a_object["__value__"], dtype=a_object["__dtype__"]
                    ).reshape(tuple(a_object["__shape__"]))
                except Exception as exc:
                    logger.debug("Error in converting: %s", exc)
                    b_object = a_object
                    raise exc
            elif a_object["__jailed_type__"] == "error":
                b_object = Exception(a_object["__value__"])
            elif a_object["__jailed_type__"] == "argument":
                b_object = a_object["__value__"]
            else:
                b_object = a_object["__value__"]
            return b_object

        if isinstance(a_object, tuple):
            a_object = list(a_object)
        isarray = isinstance(a_object, list)
        b_object = [] if isarray else dotdict()
        keys = range(len(a_object)) if isarray else a_object.keys()
        for key in keys:
            if isarray or key in a_object:
                val = a_object[key]
                if isinstance(val, (dict, list)):
                    if isarray:
                        b_object.append(self._decode(val, callback_id, with_promise))
                    else:
                        b_object[key] = self._decode(val, callback_id, with_promise)
        return b_object

    def _wrap(self, args):
        """Wrap arguments."""
        wrapped = self._encode(args)
        result = {"args": wrapped}
        return result

    def unwrap(self, args, with_promise):
        """Unwrap arguments."""
        if "callbackId" not in args:
            args["callbackId"] = None
        # wraps each callback so that the only one could be called
        result = self._decode(args["args"], args["callbackId"], with_promise)
        return result

    def set_interface(self, api):
        """Set interface."""
        if isinstance(api, dict):
            api = {a: api[a] for a in api.keys() if not a.startswith("_")}
        elif inspect.isclass(type(api)):
            api = {a: getattr(api, a) for a in dir(api) if not a.startswith("_")}
        else:
            raise Exception("unsupported api export")
        if "exit" in api:
            ext = api["exit"]

            def exit_wrapper():
                try:
                    ext()
                finally:
                    self.default_exit()

            api["exit"] = exit_wrapper
        else:
            api["exit"] = self.default_exit
        self.interface = api
        self.send_interface()

    def send_interface(self):
        """Send interface."""
        names = []
        for name in self.interface:
            if callable(self.interface[name]):
                names.append({"name": name, "data": None})
            else:
                data = self.interface[name]
                if data is not None and isinstance(data, dict):
                    data2 = {}
                    for k in data:
                        if callable(data[k]):
                            data2[k] = "**@@FUNCTION@@**:" + k
                        else:
                            data2[k] = data[k]
                    names.append({"name": name, "data": data2})
                elif isinstance(data, (str, int, float, bool)):
                    names.append({"name": name, "data": data})
        self.emit({"type": "setInterface", "api": names})

    def _gen_remote_method(self, name, plugin_id=None):
        """Return remote method."""

        def remote_method(*arguments, **kwargs):
            """Run remote method."""
            # wrap keywords to a dictionary and pass to the first argument
            if not arguments and kwargs:
                arguments = [kwargs]

            def pfunc(resolve, reject):
                resolve.__jailed_pairs__ = reject
                reject.__jailed_pairs__ = resolve
                call_func = {
                    "type": "method",
                    "name": name,
                    "pid": plugin_id,
                    "args": self._wrap(arguments),
                    "promise": self._wrap([resolve, reject]),
                }
                self.emit(call_func)

            if PYTHON34:
                return FuturePromise(pfunc, self.client.loop)
            return Promise(pfunc)

        remote_method.__remote_method = True  # pylint: disable=protected-access
        return remote_method

    def _gen_remote_callback(self, id_, arg_num, with_promise):
        """Return remote callback."""
        if with_promise:

            def remote_callback(*arguments, **kwargs):
                # wrap keywords to a dictionary and pass to the first argument
                if not arguments and kwargs:
                    arguments = [kwargs]

                def pfunc(resolve, reject):
                    resolve.__jailed_pairs__ = reject
                    reject.__jailed_pairs__ = resolve
                    self.emit(
                        {
                            "type": "callback",
                            "id": id_,
                            "num": arg_num,
                            # 'pid'  : self.id,
                            "args": self._wrap(arguments),
                            "promise": self._wrap([resolve, reject]),
                        }
                    )

                if PYTHON34:
                    return FuturePromise(pfunc, self.client.loop)
                return Promise(pfunc)

        else:

            def remote_callback(*arguments, **kwargs):
                # wrap keywords to a dictionary and pass to the first argument
                if not arguments and kwargs:
                    arguments = [kwargs]
                self.emit(
                    {
                        "type": "callback",
                        "id": id_,
                        "num": arg_num,
                        # 'pid'  : self.id,
                        "args": self._wrap(arguments),
                    }
                )

        return remote_callback

    def set_remote(self, api):
        """Set remote."""
        _remote = dotdict()
        for i, _ in enumerate(api):
            if isinstance(api[i], dict) and "name" in api[i]:
                name = api[i]["name"]
                data = api[i].get("data", None)
                if data is not None:
                    if isinstance(data, dict):
                        data2 = dotdict()
                        for key in data:
                            if key in data:
                                if data[key] == "**@@FUNCTION@@**:" + key:
                                    data2[key] = self._gen_remote_method(
                                        name + "." + key
                                    )
                                else:
                                    data2[key] = data[key]
                        _remote[name] = data2
                    else:
                        _remote[name] = data
                else:
                    _remote[name] = self._gen_remote_method(name)

        self._set_local_api(_remote)
        return _remote

    def _set_local_api(self, _remote):
        """Set local API."""
        _remote["export"] = self.set_interface
        _remote["utils"] = API_UTILS
        _remote["WORK_DIR"] = self.work_dir

        self.local["api"] = _remote

        # make a fake module with api
        mod = ModuleType("imjoy")
        sys.modules[mod.__name__] = mod  # pylint: disable=no-member
        mod.__file__ = mod.__name__ + ".py"  # pylint: disable=no-member
        mod.api = _remote


def main():
    """Run script."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=str, required=True, help="plugin id")
    parser.add_argument("--secret", type=str, required=True, help="plugin secret")
    parser.add_argument(
        "--work_dir", type=str, default=".", help="plugin working directory"
    )
    parser.add_argument(
        "--server", type=str, default="http://127.0.0.1:9527", help="socketio server"
    )
    parser.add_argument("--daemon", action="store_true", help="daemon mode")
    parser.add_argument("--debug", action="store_true", help="debug mode")

    opt = parser.parse_args()

    logging.basicConfig(stream=sys.stdout)
    logger.setLevel(logging.INFO)
    if opt.debug:
        logger.setLevel(logging.DEBUG)

    plugin_conn = PluginConnection(opt)
    plugin_conn.setup()
    plugin_conn.start()


if __name__ == "__main__":
    main()
