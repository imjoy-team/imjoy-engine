import os
from aiohttp import web
import asyncio
import socketio
import logging
import threading
import sys
import traceback
import time
import subprocess
import signal
import random
import string
import shlex
import logging
import argparse
import uuid
import shutil
import webbrowser

from subprocess import Popen, PIPE, STDOUT
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

# add executable path to PATH
os.environ['PATH'] = os.path.split(sys.executable)[0]  + os.pathsep +  os.environ.get('PATH', '')

logging.basicConfig()
logger = logging.getLogger('PluginEngine')

def get_token():
    random.seed(uuid.getnode())
    a = "%32x" % random.getrandbits(128)
    rd = a[:12] + '4' + a[13:16] + 'a' + a[17:]
    uuid4 = uuid.UUID(rd)
    random.seed()
    return str(uuid4)

parser = argparse.ArgumentParser()
parser.add_argument('--token', type=str, default=get_token(), help='connection token')
parser.add_argument('--debug', action="store_true", help='debug mode')
parser.add_argument('--serve', action="store_true", help='download ImJoy web app and serve it locally')
parser.add_argument('--host', type=str, default='localhost', help='socketio host')
parser.add_argument('--port', type=str, default='8080', help='socketio port')
opt = parser.parse_args()

if opt.serve:
    imjpath = '__ImJoy__'
    if shutil.which('git') is None:
        print('Installing git...')
        ret = subprocess.Popen("conda install -y git && git clone https://github.com/oeway/ImJoy", shell=False).wait()
        if ret != 0:
            print('Failed to install git, please check whether you have internet access.')
            sys.exit(3)
    if os.path.exists(imjpath) and os.path.isdir(imjpath):
        ret = subprocess.Popen('git pull', cwd=imjpath, shell=False).wait()
        if ret != 0:
            shutil.rmtree(imjpath)
    if not os.path.exists(imjpath):
        print('Downloading files for serving ImJoy locally...')
        ret = subprocess.Popen('git clone https://github.com/oeway/ImJoy __ImJoy__', shell=False).wait()
        if ret != 0:
            print('Failed to download files, please check whether you have internet access.')
            sys.exit(4)
    print('Now you can access your local ImJoy web app through http://'+opt.host+':'+opt.port+' , imjoy!')
    try:
        webbrowser.open('http://'+opt.host+':'+opt.port+'/#/app?token='+opt.token, new=0, autoraise=True)
    except Exception as e:
        pass
else:
    logger.info("Now you can run Python plugins from https://imjoy.io, token: %s", opt.token)
    try:
        webbrowser.open('https://imjoy.io/#/app?token='+opt.token, new=0, autoraise=True)
    except Exception as e:
        pass

MAX_ATTEMPTS = 1000
NAME_SPACE = '/'

sio = socketio.AsyncServer()
app = web.Application()
sio.attach(app)



if opt.debug:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.ERROR)

if os.path.exists('__ImJoy__/docs') and os.path.exists('__ImJoy__/docs/index.html') and os.path.exists('__ImJoy__/docs/static'):
    async def index(request):
        """Serve the client-side application."""
        with open('__ImJoy__/docs/index.html') as f:
            return web.Response(text=f.read(), content_type='text/html')
    app.router.add_static('/static', path=str('__ImJoy__/docs/static'))
    print('A local version of Imjoy web app is available at http://localhost:8080')
else:
    async def index(request):
        return web.Response(body='<H1><a href="https://imjoy.io">ImJoy.IO</a></H1><p>You can run "python -m imjoy --serve" to serve ImJoy web app locally.</p>', content_type="text/html")
app.router.add_get('/', index)

plugins = {}
plugin_cids = {}
plugin_sids = {}
clients = {}
clients_sids = {}
attempt_count = 0

cmd_history = []
default_requirements_py2 = ["psutil", "requests", "six", "websocket-client"]
default_requirements_py3 = ["psutil", "requests", "six", "websocket-client-py3"]

script_dir = os.path.dirname(os.path.normpath(__file__))
template_script = os.path.join(script_dir, 'workerTemplate.py')

if sys.platform == "linux" or sys.platform == "linux2":
    # linux
    command_template = '/bin/bash -c "source {}/bin/activate"'
    conda_activate = command_template.format("$(conda info --json -s | python -c \"import sys, json; print(json.load(sys.stdin)['conda_prefix']);\")")
elif sys.platform == "darwin":
    # OS X
    conda_activate = "source activate"
elif sys.platform == "win32":
    # Windows...
    conda_activate = "activate"
else:
    conda_activate = "conda activate"


@sio.on('connect', namespace=NAME_SPACE)
def connect(sid, environ):
    logger.info("connect %s", sid)

@sio.on('init_plugin', namespace=NAME_SPACE)
async def on_init_plugin(sid, kwargs):

    if sid in clients_sids:
        client_id = clients_sids[sid]
    else:
        logger.debug('client %s is not registered.', sid)
        return {'success': False}
        # client_id = ''
        # clients_sids[sid] = client_id
        # if client_id in clients:
        #     clients[client_id].append(sid)
        # else:
        #     clients[client_id] = [sid]


    pid = kwargs['id']
    config = kwargs.get('config', {})
    env = config.get('env', None)
    cmd = config.get('cmd', 'python')
    pname = config.get('name', None)
    requirements = config.get('requirements', []) or []

    logger.info("initialize the plugin. name=%s, id=%s, cmd=%s", pname, id, cmd)

    if pid in plugins:
        if client_id in plugin_cids:
            plugin_cids[client_id].append(plugins[pid])
        else:
            plugin_cids[client_id] = [plugins[pid]]
        logger.debug('plugin already initialized: %s', pid)
        await sio.emit('message_from_plugin_'+pid, {"type": "initialized", "dedicatedThread": True})
        return {'success': True, 'secret': plugins[pid]['secret']}

    env_name = ''
    is_py2 = False

    if env is not None:
        try:
            if not env.startswith('conda'):
                raise Exception('env command must start with conda')
            if 'python=2' in env:
                is_py2 = True
            parms = shlex.split(env)
            if '-n' in parms:
                env_name = parms[parms.index('-n') + 1]
            elif '--name' in parms:
                env_name = parms[parms.index('--name') + 1]
            elif pname is not None:
                env_name = pname.replace(' ', '_')
                env = env.replace('create', 'create -n '+env_name)

            if '-y' not in parms:
                env = env.replace('create', 'create -y')

            logger.info('creating environment: %s', env)
            if env not in cmd_history:
                subprocess.Popen(env, shell=False).wait()
                cmd_history.append(env)
            else:
                logger.debug('skip command: %s', env)
        except Exception as e:
            await sio.emit('message_from_plugin_'+pid,  {"type": "executeFailure", "error": "failed to create environment."})
            logger.error('failed to execute plugin: %s', str(e))

    if type(requirements) is list:
        requirements_pip = " ".join(requirements)
    elif type(requirements) is str:
        requirements_pip = "&& " + requirements
    else:
        raise Exception('wrong requirements type.')
    requirements_cmd = "pip install "+" ".join(default_requirements_py2 if is_py2 else default_requirements_py3) + ' ' + requirements_pip
    # if env_name is not None:
    requirements_cmd = conda_activate + " "+ env_name + " && " + requirements_cmd
    # if env_name is not None:
    cmd = conda_activate + " " + env_name + " && " + cmd


    secretKey = str(uuid.uuid4())
    plugins[pid] = {'secret': secretKey, 'id': pid, 'name': config['name'], 'type': config['type'], 'client_id': client_id}
    if client_id in plugin_cids:
        plugin_cids[client_id].append(plugins[pid])
    else:
        plugin_cids[client_id] = [plugins[pid]]

    @sio.on('from_plugin_'+secretKey, namespace=NAME_SPACE)
    async def message_from_plugin(sid, kwargs):
        # print('forwarding message_'+secretKey, kwargs)
        if kwargs['type'] in ['initialized', 'importSuccess', 'importFailure', 'executeSuccess', 'executeFailure']:
            if pid in plugins:
                plugin_sids[sid] = plugins[pid]
            await sio.emit('message_from_plugin_'+pid,  kwargs)
            logger.debug('message from %s', pid)
        else:
            await sio.emit('message_from_plugin_'+pid, {'type': 'message', 'data': kwargs})

    @sio.on('message_to_plugin_'+pid, namespace=NAME_SPACE)
    async def message_to_plugin(sid, kwargs):
        # print('forwarding message_to_plugin_'+pid, kwargs)
        if kwargs['type'] == 'message':
            await sio.emit('to_plugin_'+secretKey, kwargs['data'])
        logger.debug('message to plugin %s', secretKey)

    try:
        abort = threading.Event()
        plugins[pid]['abort'] = abort #
        taskThread = threading.Thread(target=execute, args=[requirements_cmd, cmd+' '+template_script+' --id='+pid+' --host='+opt.host+' --port='+opt.port+' --secret='+secretKey+' --namespace='+NAME_SPACE, './', abort, pid])
        taskThread.daemon = True
        taskThread.start()
        # execute('python pythonWorkerTemplate.py', './', abort, pid)
        return {'success': True, 'secret': secretKey}
    except Exception as e:
        logger.error(e)
        return {'success': False}



@sio.on('kill_plugin', namespace=NAME_SPACE)
async def on_kill_plugin(sid, kwargs):
    pid = kwargs['id']
    if pid in plugins:
        print('killing plugin ' + pid)
        await sio.emit('to_plugin_'+plugins[pid]['secret'], {'type': 'disconnect'})

    return {'success': True}


@sio.on('register_client', namespace=NAME_SPACE)
async def on_register_client(sid, kwargs):
    global attempt_count
    cid = kwargs['id']
    token = kwargs.get('token', None)
    if token != opt.token:
        logger.debug('token mismatch: %s != %s', token, opt.token)
        print('======== Connection Token: '+opt.token + ' ========')
        attempt_count += 1
        if attempt_count>= MAX_ATTEMPTS:
            logger.info("Client exited because max attemps exceeded: %s", attempt_count)
            sys.exit(100)
        return {'plugins': [], 'success': False}
    else:
        attempt_count = 0
        if cid in clients:
            clients[cid].append(sid)
        else:
            clients[cid] = [sid]
        clients_sids[sid] = cid
        logger.info("register client: %s", kwargs)
        return {'success': True, 'plugins': [ {"id": p['id'], "name": p['name'], "type": p['type']} for p in plugin_cids[cid] ] if cid in plugin_cids else []}

def scandir(path, type=None, recursive=False):
    file_list = []
    for f in os.scandir(path):
        if f.name.startswith('.'):
            continue
        if type is None or type == 'file':
            if os.path.isdir(f.path):
                if recursive:
                    file_list.append({'name': f.name, 'type': 'dir', 'children': scandir(f.path, type, recursive)})
                else:
                    file_list.append({'name': f.name, 'type': 'dir'})
            else:
                file_list.append({'name': f.name, 'type': 'file'})
        elif type == 'directory':
            if os.path.isdir(f.path):
                file_list.append({'name': f.name})
    return file_list

@sio.on('list_dir', namespace=NAME_SPACE)
async def on_list_dir(sid, kwargs):
    if sid not in clients_sids:
        logger.debug('client %s is not registered.', sid)
        return {'success': False}
    path = kwargs.get('path', '.')
    type = kwargs.get('type', None)
    recursive = kwargs.get('recursive', False)
    files_list = {'success': True}
    path = os.path.normpath(path)
    files_list['path'] = path
    files_list['name'] = os.path.basename(os.path.abspath(path))
    files_list['type'] = 'dir'

    files_list['children'] = scandir(files_list['path'], type, recursive)
    return files_list

@sio.on('message', namespace=NAME_SPACE)
async def on_message(sid, kwargs):
    logger.info("message recieved: %s", kwargs)

@sio.on('disconnect', namespace=NAME_SPACE)
async def disconnect(sid):
    if sid in clients_sids:
        cid = clients_sids[sid]
        del clients_sids[sid]
        if cid in clients and sid in clients[cid]:
            clients[cid].remove(sid)
        if cid in clients or len(clients[cid])==0:
            if cid in plugin_cids:
                for plugin in plugin_cids[cid]:
                    await on_kill_plugin(sid, plugin)
                del plugin_cids[cid]

    # plugin is terminating
    if sid in plugin_sids:
        pid = plugin_sids[sid]['id']
        if pid in plugins:
            del plugins[pid]
        del plugin_sids[sid]
        for cid in plugin_cids.keys():
            exist = False
            for p in plugin_cids[cid]:
                if p['id'] == pid:
                    exist = p
            if exist:
                plugin_cids[cid].remove(exist)
    logger.info('disconnect %s', sid)


def process_output(line):
    print(line)
    return True

def execute(requirements_cmd, args, workdir, abort, name):
    try:
        logger.info('installing requirements: %s', requirements_cmd)
        if requirements_cmd not in cmd_history:
            ret = subprocess.Popen(requirements_cmd, shell=True).wait()
            if ret != 0:
                git_cmd = ''
                if shutil.which('git') is None:
                    git_cmd += " git"
                if shutil.which('pip') is None:
                    git_cmd += " pip"
                if git_cmd != '':
                    logger.info('pip command failed, trying to install git and pip...')
                    # try to install git and pip
                    git_cmd = "conda install -y" + git_cmd
                    ret = subprocess.Popen(git_cmd, shell=False).wait()
                    if ret != 0:
                        raise Exception('Failed to install git/pip and dependencies with exit code: '+str(ret))
                    else:
                        ret = subprocess.Popen(requirements_cmd, shell=True).wait()
                        if ret != 0:
                            raise Exception('Failed to install dependencies with exit code: '+str(ret))
                else:
                    raise Exception('Failed to install dependencies with exit code: '+str(ret))
            cmd_history.append(requirements_cmd)
        else:
            logger.debug('skip command: %s', requirements_cmd)
    except Exception as e:
        # await sio.emit('message_from_plugin_'+pid,  {"type": "executeFailure", "error": "failed to install requirements."})
        logger.error('failed to execute plugin: %s', str(e))

    env = os.environ.copy()
    if type(args) is str:
        args = args.split()
    if not args:
        args = []
    # Convert them all to strings
    args = [str(x) for x in args if str(x) != '']
    logger.info('%s task started.', name)
    unrecognized_output = []
    env['PYTHONPATH'] = os.pathsep.join(
        ['.', workdir, env.get('PYTHONPATH', '')] + sys.path)

    args = ' '.join(args)
    logger.info('Task subprocess args: %s', args)

    # set system/version dependent "start_new_session" analogs
    # https://docs.python.org/2/library/subprocess.html#converting-argument-sequence
    kwargs = {}
    if sys.platform != "win32":
        kwargs.update(preexec_fn=os.setsid)

    try:
        # we use shell mode, so it won't work nicely on windows
        p = Popen(args, bufsize=0, stdout=PIPE, stderr=STDOUT,
                  shell=True, universal_newlines=True, **kwargs)
        pid = p.pid
    except Exception as e:
        print('error from task:', e)
        # traceback.print_exc()
        #task.set('status.error', # traceback.format_exc())
        # end(force_quit=True)
        return False
    # run the shell as a subprocess:

    nbsr = NonBlockingStreamReader(p.stdout)
    try:
        sigterm_time = None  # When was the SIGTERM signal sent
        sigterm_timeout = 2  # When should the SIGKILL signal be sent
        # get the output
        endofstream = False
        while p.poll() is None or not endofstream:
            try:
                line = nbsr.readline(0.1)
            except(UnexpectedEndOfStream):
                line = None
                endofstream = True

            if line is not None:
                # Remove whitespace
                line = line.strip()
            if line:
                try:
                    if not process_output(line):
                        logger.warning('%s unrecognized output: %s' % (name, line.strip()))
                        unrecognized_output.append(line)
                except Exception as e:
                    print('error from task:', e)
                    # traceback.print_exc()
                    #task.set('status.error', # traceback.format_exc())
            else:
                time.sleep(0.05)

            if abort.is_set():
                if sigterm_time is None:
                    # Attempt graceful shutdown
                    p.send_signal(signal.SIGINT)
                    p.send_signal(signal.SIGTERM)
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                    except Exception as e:
                        pass
                    sigterm_time = time.time()
            if sigterm_time is not None and (time.time() - sigterm_time > sigterm_timeout):
                p.send_signal(signal.SIGKILL)
                logger.warning('Sent SIGKILL to task "%s"' % name)
                time.sleep(0.1)
    except:
        # traceback.print_exc()
        try:
            p.terminate()
        except Exception as e:
            logger.info('error occured during terminating a process.')
        raise
    if abort.is_set():
        return False
    elif p.returncode != 0:
        # Report that this task is finished
        logger.error('%s task failed with error code %s' %
                          (name, str(p.returncode)))
        # if exception is None:
        #     exception = 'error code %s' % str(p.returncode)
        #     if unrecognized_output:
        #         if traceback is None:
        #             traceback = '\n'.join(unrecognized_output)
        #         else:
        #             traceback = traceback + \
        #                 ('\n'.join(unrecognized_output))
        logger.info('error from task %s', p.returncode)
        return False
    else:
        logger.info('%s task completed.', name)
        return True

class NonBlockingStreamReader:

    def __init__(self, stream):
        '''
        stream: the stream to read from.
                Usually a process' stdout or stderr.
        '''
        self._s = stream
        self._q = Queue()

        def _populateQueue(stream, queue):
            '''
            Collect lines from 'stream' and put them in 'quque'.
            '''

            while True:
                line = stream.readline()
                if line:
                    queue.put(line)
                else:
                    self.end = True
                    break
                    #raise UnexpectedEndOfStream
                time.sleep(0.01)
        self.end = False
        self._t = threading.Thread(target=_populateQueue,
                                   args=(self._s, self._q))
        self._t.daemon = True
        self._t.start()  # start collecting lines from the stream

    def readline(self, timeout=None):
        try:
            return self._q.get(block=timeout is not None,
                               timeout=timeout)
        except Empty:
            if self.end:
                raise UnexpectedEndOfStream
            return None

class UnexpectedEndOfStream(Exception):
    pass



print('======>> Connection Token: '+opt.token + ' <<======')
try:
    web.run_app(app, host=opt.host, port=opt.port)
finally:
    print('closing plugins...')
    loop = asyncio.get_event_loop()
    for sid in plugin_sids:
        try:
            loop.run_until_complete(on_kill_plugin(sid, {"id":plugin_sids[sid]['id']}))
        finally:
            pass
    loop.close()
    time.sleep(0.2)
    print('done.')
