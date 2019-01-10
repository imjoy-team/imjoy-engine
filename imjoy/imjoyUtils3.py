import asyncio
import sys
import traceback
import inspect

from imjoyUtils import Promise

async def task_worker(self, async_q, logger, abort=None):
    while True:
        if abort is not None and abort.is_set():
            break
        d = await async_q.get()
        try:
            if d is None:
                continue
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
            elif d['type'] == 'execute':
                if not self._executed:
                    try:
                        type = d['code']['type']
                        content = d['code']['content']
                        exec(content, self._local)
                        self._executed = True
                        self.emit({'type':'executeSuccess'})
                    except Exception as e:
                        logger.info('error during execution: %s', traceback.format_exc())
                        self.emit({'type':'executeFailure', 'error': repr(e)})
            elif d['type'] == 'method':
                if d['name'] in self._interface:
                    if 'promise' in d:
                        try:
                            resolve, reject = self._unwrap(d['promise'], False)
                            method = self._interface[d['name']]
                            args = self._unwrap(d['args'], True)
                            # args.append({'id': self.id})
                            result = method(*args)
                            if result is not None and inspect.isawaitable(result):
                                result = await result
                            resolve(result)
                        except Exception as e:
                            logger.error('error in method %s: %s', d['name'], traceback.format_exc())
                            reject(e)
                    else:
                        try:
                            method = self._interface[d['name']]
                            args = self._unwrap(d['args'], True)
                            # args.append({'id': self.id})
                            result = method(*args)
                            if result is not None and inspect.isawaitable(result):
                                await result
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
                        if result is not None and inspect.isawaitable(result):
                            result = await result
                        resolve(result)
                    except Exception as e:
                        logger.error('error in method %s: %s', d['id'], traceback.format_exc())
                        reject(e)
                else:
                    try:
                        method = self._store.fetch(d['id'])[d['num']]
                        args = self._unwrap(d['args'], True)
                        # args.append({'id': self.id})
                        result = method(*args)
                        if result is not None and inspect.isawaitable(result):
                            await reresultt
                    except Exception as e:
                        logger.error('error in method %s: %s', d['id'], traceback.format_exc())
        except Exception as e:
            print('error occured in the loop.', e)
        finally:
            sys.stdout.flush()
            async_q.task_done()


class FuturePromise(Promise, asyncio.Future):
    def __init__(self, pfunc, loop):
        self.loop = loop
        Promise.__init__(self, pfunc)
        asyncio.Future.__init__(self)

    def resolve(self, result):
        if self._resolve_handler or self._finally_handler:
            Promise.resolve(self, result)
        else:
            self.loop.call_soon(self.set_result, result)


    def reject(self, error):
        if self._catch_handler or self._finally_handler:
            Promise.reject(self, error)
        else:
            if error:
                self.loop.call_soon(self.set_exception, Exception())
            else:
                self.loop.call_soon(self.set_exception, Exception(str(error)))
