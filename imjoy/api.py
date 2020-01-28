class API():
    def __init__(self):
        self._tape = []
        self._config = None

    def __getattr__(self, name):
        if name == 'export':
            def register_new_plugin(*args, **kwargs):
                self._tape.append({'name': name, 'args': args, 'kwargs': kwargs})
                if 'config' in kwargs:
                    self._config = kwargs['config']
            return register_new_plugin
        else:
            def record_action(*args, **kwargs):
                self._tape.append({'name': name, 'args': args, 'kwargs': kwargs})

            return record_action

    def summary(self):
        for act in self._tape:
            print('==> '+act['name'] + ' args: ' + str(act['args']) + '  kwargs: '+str(act['kwargs']))

api = API()