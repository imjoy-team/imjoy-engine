import argparse
import logging
import time
import os
import sys
import six
import random
import math
import traceback
import uuid
from functools import reduce
import inspect
import psutil
import threading
from socketIO_client import SocketIO, LoggingNamespace

try:
    import queue
except ImportError:
    import Queue as queue

logging.basicConfig()
logger = logging.getLogger('plugin')
logger.setLevel(logging.INFO)
# import logging
# logging.basicConfig(level=logging.DEBUG)
ARRAY_CHUNK = 1000000

if '' not in sys.path:
    sys.path.insert(0, '')

imjoy_path = os.path.dirname(os.path.normpath(__file__))
if imjoy_path not in sys.path:
    sys.path.insert(0, imjoy_path)

def setInterval(interval):
    def decorator(function):
        def wrapper(*args, **kwargs):
            stopped = threading.Event()
            def loop(): # executed in another thread
                while not stopped.wait(interval): # until stopped
                    function(*args, **kwargs)
            t = threading.Thread(target=loop)
            t.daemon = True # stop if the program exits
            t.start()
            return stopped
        return wrapper
    return decorator


class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

class Promise(object):
    def resolve(self, result):
        try:
            if self._resolve_handler:
                self._resolve_handler(result)
        except Exception as e:
            if self._catch_handler:
                self._catch_handler(e)
            elif not self._finally_handler:
                logger.error('Uncaught Exception: '+ str(e))
        finally:
            if self._finally_handler:
                self._finally_handler()

    def reject(self, error):
        try:
            if self._catch_handler:
                self._catch_handler(error)
            elif not self._finally_handler:
                logger.error('Uncaught Exception: '+ str(error))
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
        pfunc(self.resolve, self.reject)


class ReferenceStore():
    def __init__(self):
        self._store = {}
        self._indices = [0]

    def _genId(self):
        if len(self._indices) == 1:
            self._indices[0] += 1
            id = self._indices[0]
        else:
            id = self._indices.pop(0)
        return id

    def _releaseId(self, id):
        for i in range(len(self._indices)):
            if id < self._indices[i]:
                self._indices.insert(i, id)
                break

        # cleaning-up the sequence tail
        for i in reversed(range(len(self._indices))):
            if self._indices[i]-1 == self._indices[i-1]:
                self._indices.pop()
            else:
                break

    def put(self, obj):
        id = self._genId()
        self._store[id] = obj
        return id

    def fetch(self, id):
        obj = self._store[id]
        self._store[id] = None
        del self._store[id]
        self._releaseId(id)
        return obj

def kill(proc_pid):
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()

api_utils = dotdict(kill=kill)

class PluginConnection():
    def __init__(self, pid, secret, protocol='http', host='localhost', port=8080, namespace='/', api=None):
        socketIO = SocketIO(host, port, LoggingNamespace)
        self.socketIO = socketIO
        self._init = False
        self.secret = secret
        self.id = pid
        def emit(msg):
            socketIO.emit('from_plugin_'+ secret, msg)
        self.emit = emit

        self._local = {}
        _remote = dotdict()
        self._setLocalAPI(_remote)
        self._interface = {}
        self._remote_set = False
        self._store = ReferenceStore()
        self._executed = False
        self.q = queue.Queue()

        self._init = False
        sys.stdout.flush()
        socketIO.on('to_plugin_'+secret, self.sio_plugin_message)
        self.emit({"type": "initialized", "dedicatedThread": True})

        def on_disconnect():
            self.exit(1)
        socketIO.on('disconnect', on_disconnect)

        t = threading.Thread(target=self.message_handler, args=(self.q,))
        t.daemon = True
        t.start()

    def wait_forever(self):
        self.socketIO.wait()

    def exit(self, code):
        if 'exit' in self._interface:
            try:
                self._interface['exit']()
            except Exception as e:
                logger.error('Error when exiting: %s', e)
                sys.exit(1)
            else:
                logger.info('terminating plugin')
                sys.exit(code)
        else:
            sys.exit(0)

    def _encode(self, aObject, callbacks):
        if aObject is None:
            return aObject
        if type(aObject) is tuple:
            aObject = list(aObject)
        isarray = type(aObject) is list
        bObject = [] if isarray else {}
        #skip if already encoded
        if type(aObject) is dict and '__jailed_type__' in aObject and '__value__' in aObject:
            return aObject
        keys = range(len(aObject)) if isarray else aObject.keys()
        for k in keys:
            v = aObject[k]
            value = None
            if callable(v):
                interfaceFuncName = None
                for name in self._interface:
                    if self._interface[name] == v:
                        interfaceFuncName = name
                        break
                if interfaceFuncName is None:
                    cid = str(uuid.uuid4())
                    callbacks[cid] = v
                    vObj = {'__jailed_type__': 'callback', '__value__' : 'f', 'num': cid}
                else:
                    vObj = {'__jailed_type__': 'interface', '__value__' : interfaceFuncName}

          # // send objects supported by structure clone algorithm
          # // https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Structured_clone_algorithm
            #if(v !== Object(v) || v instanceof Boolean || v instanceof String || v instanceof Date || v instanceof RegExp || v instanceof Blob || v instanceof File || v instanceof FileList || v instanceof ArrayBuffer || v instanceof ArrayBufferView || v instanceof ImageData){
            elif 'np' in self._local and isinstance(v, (self._local['np'].ndarray, self._local['np'].generic)):
                vb = bytearray(v.tobytes())
                if len(vb)>ARRAY_CHUNK:
                    vl = int(math.ceil(1.0*len(vb)/ARRAY_CHUNK))
                    v_bytes = []
                    for i in range(vl):
                        v_bytes.append(vb[i*ARRAY_CHUNK:(i+1)*ARRAY_CHUNK])
                else:
                    v_bytes = vb
                vObj = {'__jailed_type__': 'ndarray', '__value__' : v_bytes, '__shape__': v.shape, '__dtype__': str(v.dtype)}
            elif type(v) is dict or type(v) is list:
                vObj = self._encode(v, callbacks)
            elif not isinstance(v, six.string_types) and type(v) is bytes:
                vObj = v.decode() # covert python3 bytes to str
            elif isinstance(v, Exception):
                vObj = {'__jailed_type__': 'error', '__value__' : str(v)}
            else:
                vObj = {'__jailed_type__': 'argument', '__value__' : v}

            if isarray:
                bObject.append(vObj)
            else:
                bObject[k] = vObj

        return bObject

    def _genRemoteCallback(self, id, argNum, withPromise):
        if withPromise:
            def remoteCallback(*arguments, **kwargs):
                # wrap keywords to a dictionary and pass to the first argument
                if len(arguments) == 0 and len(kwargs) > 0:
                    arguments = [kwargs]
                def p(resolve, reject):
                    self.emit({
                        'type' : 'callback',
                        'id'   : id,
                        'num'  : argNum,
                        # 'pid'  : self.id,
                        'args' : self._wrap(arguments),
                        'promise': self._wrap([resolve, reject])
                    })
                    time.sleep(0)
                return Promise(p)
        else:
            def remoteCallback(*arguments, **kwargs):
                # wrap keywords to a dictionary and pass to the first argument
                if len(arguments) == 0 and len(kwargs) > 0:
                    arguments = [kwargs]
                ret = self.emit({
                    'type' : 'callback',
                    'id'   : id,
                    'num'  : argNum,
                    # 'pid'  : self.id,
                    'args' : self._wrap(arguments)
                })
                time.sleep(0)
                return ret
        return remoteCallback

    def _decode(self, aObject, callbackId, withPromise):
        if aObject is None:
            return aObject
        if '__jailed_type__' in aObject and '__value__' in aObject:
            if aObject['__jailed_type__'] == 'callback':
                bObject = self._genRemoteCallback(callbackId, aObject['num'], withPromise)
            elif aObject['__jailed_type__'] == 'interface':
                name = aObject['__value__']
                if name in self._remote:
                    bObject = self._remote[name]
                else:
                    bObject = self._genRemoteMethod(name)
            elif aObject['__jailed_type__'] == 'ndarray':
                # create build array/tensor if used in the plugin
                try:
                    np = self._local['np']
                    if isinstance(aObject['__value__'], bytearray):
                        aObject['__value__'] = aObject['__value__']
                    elif isinstance(aObject['__value__'], list) or isinstance(aObject['__value__'], tuple):
                        aObject['__value__'] = reduce((lambda x, y: x + y), aObject['__value__'])
                    else:
                        raise Exception('Unsupported data type: ', type(aObject['__value__']), aObject['__value__'])
                    bObject = np.frombuffer(aObject['__value__'], dtype=aObject['__dtype__']).reshape(tuple(aObject['__shape__']))
                except Exception as e:
                    logger.debug('Error in converting: %s', e)
                    bObject = aObject
                    raise e
            elif aObject['__jailed_type__'] == 'error':
                bObject = Exception(aObject['__value__'])
            elif aObject['__jailed_type__'] == 'argument':
                bObject = aObject['__value__']
            else:
                bObject = aObject['__value__']
            return bObject
        else:
            if type(aObject) is tuple:
                aObject = list(aObject)
            isarray = type(aObject) is list
            bObject =  [] if isarray else dotdict()
            keys = range(len(aObject)) if isarray else aObject.keys()
            for k in keys:
                if isarray or k in aObject:
                    v = aObject[k]
                    if isinstance(v, dict)or type(v) is list:
                        if isarray:
                            bObject.append(self._decode(v, callbackId, withPromise))
                        else:
                            bObject[k] = self._decode(v, callbackId, withPromise)
            return bObject

    def _wrap(self, args):
        callbacks = {}
        wrapped = self._encode(args, callbacks)
        result = {'args': wrapped}
        if len(callbacks.keys()) > 0:
            result['callbackId'] = self. _store.put(callbacks)
        return result

    def _unwrap(self, args, withPromise):
        called = False
        if "callbackId" not in args:
            args["callbackId"] = None
        # wraps each callback so that the only one could be called
        result = self._decode(args["args"], args["callbackId"], withPromise)
        return result

    def _ndarray(self, typedArray, shape, dtype):
        _dtype = type(typedArray)
        if dtype and dtype != _dtype:
            raise Exception("dtype doesn't match the type of the array: "+_dtype+' != '+dtype)
        shape = shape or (len(typedArray), )
        return {"__jailed_type__": 'ndarray', "__value__" : typedArray, "__shape__": shape, "__dtype__": _dtype}

    def setInterface(self, api):
        if inspect.isclass(type(api)):
            api = {a:getattr(api, a) for a in dir(api) if not a.startswith('_')}
        self._interface = api
        self._sendInterface()

    def _sendInterface(self):
        names = []
        for name in self._interface:
            if callable(self._interface[name]):
                names.append({"name":name, "data": None})
            else:
                data = self._interface[name]
                if data is not None and type(data) is dict:
                    data2 = {}
                    for k in data:
                        if callable(data[k]):
                            data2[k] = "**@@FUNCTION@@**:"+k
                        else:
                            data2[k] = data[k]
                    names.append({"name":name, "data": data2})
                else:
                  names.append({"name":name, "data": data})
        self.emit({'type':'setInterface', 'api': names})

    def _genRemoteMethod(self, name):
        def remoteMethod(*arguments, **kwargs):
            # wrap keywords to a dictionary and pass to the first argument
            if len(arguments) == 0 and len(kwargs) > 0:
                arguments = [kwargs]
            def p(resolve, reject):
                call_func = {
                    'type': 'method',
                    'name': name,
                    'args': self._wrap(arguments),
                    # 'pid'  : self.id,
                    'promise': self._wrap([resolve, reject])
                }
                self.emit(call_func)
                time.sleep(0)
            return Promise(p)

        return remoteMethod

    def _setRemote(self, api):
        _remote = dotdict()
        for i in range(len(api)):
            name = api[i]["name"]
            data = api[i]["data"]
            if data is not None:
                if type(data) == 'dict':
                    data2 = {}
                    for key in data:
                        if key in data:
                            if data[key] == "**@@FUNCTION@@**:"+key:
                                data2[key] = self._genRemoteMethod(name+'.'+key)
                            else:
                                data2[key] = data[key]
                    _remote[name] = data2
                else:
                    _remote[name] = data
            else:
                _remote[name] = self._genRemoteMethod(name)
        self._setLocalAPI(_remote)
        return _remote

    def _setLocalAPI(self, _remote):
        _remote["ndarray"] = self._ndarray
        _remote["export"] = self.setInterface
        _remote["utils"] = api_utils
        self._local["api"] = _remote

    def sio_plugin_message(self, *args):
        data = args[0]
        if data['type']== 'import':
            self.emit({'type':'importSuccess', 'url': data['url']})
        elif data['type']== 'disconnect':
            self.exit(0)
        else:
            if data['type'] == 'execute':
                if not self._executed:
                    try:
                        type = data['code']['type']
                        content = data['code']['content']
                        exec(content, self._local)
                        self.emit({'type':'executeSuccess'})
                        self._executed = True
                    except Exception as e:
                        logger.info('error during execution: %s', traceback.format_exc())
                        self.emit({'type':'executeFailure', 'error': repr(e)})
                else:
                    logger.debug('skip execution.')
                    self.emit({'type':'executeSuccess'})
            elif data['type'] == 'message':
                d = data['data']
                if d['type'] == 'getInterface':
                    self._sendInterface()
                elif d['type'] == 'setInterface':
                    self._setRemote(d['api'])
                    self.emit({'type':'interfaceSetAsRemote'})
                    if not self._init:
                        self.emit({'type':'getInterface'})
                        self._init = True
                elif d['type'] == 'interfaceSetAsRemote':
                    #self.emit({'type':'getInterface'})
                    self._remote_set = True
                else:
                    self.q.put(d)
                    logger.debug('added task to the queue')
                sys.stdout.flush()
                time.sleep(0)

    def message_handler(self, q):
        while True:
            try:
                d = q.get()
                q.task_done()
                if d is not None and d['type'] == 'method':
                    if d['name'] in self._interface:
                        if 'promise' in d:
                            try:
                                resolve, reject = self._unwrap(d['promise'], False)
                                method = self._interface[d['name']]
                                args = self._unwrap(d['args'], True)
                                # args.append({'id': self.id})
                                result = method(*args)
                                resolve(result)
                            except Exception as e:
                                logger.error('error in method %s: %s', d['name'], traceback.format_exc())
                                reject(e)
                        else:
                            try:
                                method = self._interface[d['name']]
                                args = self._unwrap(d['args'], True)
                                # args.append({'id': self.id})
                                method(*args)
                            except Exception as e:
                                logger.error('error in method %s: %s', d['name'], traceback.format_exc())
                    else:
                        raise Exception('method '+d['name'] +' is not found.')
                elif d['type'] == 'callback':
                    if 'promise' in d:
                        try:
                            resolve, reject = self._unwrap(d['promise'], False)
                            method = self._store.fetch(d['id'])[d['num']]
                            args = self._unwrap(d['args'], True)
                            # args.append({'id': self.id})
                            result = method(*args)
                            resolve(result)
                        except Exception as e:
                            logger.error('error in method %s: %s', d['id'], traceback.format_exc())
                            reject(e)
                    else:
                        try:
                            method = self._store.fetch(d['id'])[d['num']]
                            args = self._unwrap(d['args'], True)
                            # args.append({'id': self.id})
                            method(*args)
                        except Exception as e:
                            logger.error('error in method %s: %s', d['id'], traceback.format_exc())
            except queue.Empty:
                time.sleep(0.1)
            finally:
                time.sleep(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', type=str, required=True, help='plugin id')
    parser.add_argument('--secret', type=str, required=True, help='plugin secret')
    parser.add_argument('--namespace', type=str, default='/', help='socketio namespace')
    parser.add_argument('--host', type=str, default='localhost', help='socketio host')
    parser.add_argument('--port', type=str, default='8080', help='socketio port')
    parser.add_argument('--debug', action="store_true", help='debug mode')
    opt = parser.parse_args()
    if opt.debug:
        logger.setLevel(logging.DEBUG)
    pc = PluginConnection(opt.id, opt.secret, host=opt.host, port=int(opt.port))
    pc.wait_forever()
