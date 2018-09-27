import os
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
import psutil
from aiohttp import web, WSCloseCode

try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

# add executable path to PATH
os.environ['PATH'] = os.path.split(sys.executable)[0]  + os.pathsep +  os.environ.get('PATH', '')

logging.basicConfig(stream=sys.stdout)
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
parser.add_argument('--workspace', type=str, default='~/ImJoyWorkspace', help='workspace folder for plugins')
opt = parser.parse_args()

WORKSPACE_DIR = os.path.expanduser(opt.workspace)
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

if opt.serve:
    imjpath = '__ImJoy__'
    if shutil.which('git') is None:
        print('Installing git...')
        ret = subprocess.Popen("conda install -y git && git clone https://github.com/oeway/ImJoy".split(), shell=False).wait()
        if ret != 0:
            print('Failed to install git, please check whether you have internet access.')
            sys.exit(3)
    if os.path.exists(imjpath) and os.path.isdir(imjpath):
        ret = subprocess.Popen(['git', 'pull'], cwd=imjpath, shell=False).wait()
        if ret != 0:
            shutil.rmtree(imjpath)
    if not os.path.exists(imjpath):
        print('Downloading files for serving ImJoy locally...')
        ret = subprocess.Popen('git clone https://github.com/oeway/ImJoy __ImJoy__'.split(), shell=False).wait()
        if ret != 0:
            print('Failed to download files, please check whether you have internet access.')
            sys.exit(4)
    print('Now you can access your local ImJoy web app through http://'+opt.host+':'+opt.port+' , imjoy!')
    try:
        webbrowser.get(using='chrome').open('http://'+opt.host+':'+opt.port+'/#/app?token='+opt.token, new=0, autoraise=True)
    except Exception as e:
        try:
            webbrowser.open('http://'+opt.host+':'+opt.port+'/about?token='+opt.token, new=0, autoraise=True)
        except Exception as e:
            print('Failed to open the browser.')

else:
    logger.info("Now you can run Python plugins from https://imjoy.io, token: %s", opt.token)
    try:
        webbrowser.get(using='chrome').open('http://'+opt.host+':'+opt.port+'/about?token='+opt.token, new=0, autoraise=True)
    except Exception as e:
        try:
            webbrowser.open('http://'+opt.host+':'+opt.port+'/about?token='+opt.token, new=0, autoraise=True)
        except Exception as e:
            print('Failed to open the browser.')

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

async def about(request):
    params = request.rel_url.query
    if 'token' in params:
        body = '<H1><a href="https://imjoy.io/#/app?token='+params['token']+'">Open ImJoy App</a></H1><br> <p>Connection token: '+params['token'] + '</p>'
    else:
        body = '<H1><a href="https://imjoy.io/#/app">Open ImJoy App</a></H1>'
    body += '<p>Note: you need to install Google Chrome browser for access all the features of ImJoy. <a href="https://www.google.com/chrome/">Download Chrome</a></p>'
    return web.Response(body=body, content_type="text/html")

app.router.add_get('/', index)
app.router.add_get('/about', about)

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
template_script = os.path.abspath(os.path.join(script_dir, 'workerTemplate.py'))

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
    workspace = config.get('workspace', 'default')
    work_dir = os.path.join(WORKSPACE_DIR, workspace)
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)
    plugin_env = os.environ.copy()
    plugin_env['WORK_DIR'] = work_dir

    logger.info("initialize the plugin. name=%s, id=%s, cmd=%s, workspace=%s", pname, id, cmd, workspace)

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
        taskThread = threading.Thread(target=launch_plugin, args=[env, requirements_cmd, cmd+' '+template_script+' --id='+pid+' --host='+opt.host+' --port='+opt.port+' --secret='+secretKey+' --namespace='+NAME_SPACE + ' --work_dir='+work_dir, work_dir, abort, pid, plugin_env])
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
        plugins[pid]['abort'].set()
    return {'success': True}


@sio.on('register_client', namespace=NAME_SPACE)
async def on_register_client(sid, kwargs):
    global attempt_count
    cid = kwargs['id']
    token = kwargs.get('token', None)
    if token != opt.token:
        logger.debug('token mismatch: %s != %s', token, opt.token)
        print('======== Connection Token: '+opt.token + ' ========')
        try:
            webbrowser.open('http://'+opt.host+':'+opt.port+'/about?token='+opt.token, new=0, autoraise=True)
        except Exception as e:
            print('Failed to open the browser.')
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
    sys.stdout.flush()
    return True

def launch_plugin(env, requirements_cmd, args, work_dir, abort, name, plugin_env):
    if abort.is_set():
        logger.info('plugin aborting...')
        return False
    try:
        logger.info('creating environment: %s', env)
        if env not in cmd_history:
            subprocess.Popen(env.split(), shell=False, env=plugin_env, cwd=work_dir).wait()
            cmd_history.append(env)
        else:
            logger.debug('skip command: %s', env)

        if abort.is_set():
            logger.info('plugin aborting...')
            return False

        logger.info('installing requirements: %s', requirements_cmd)
        if requirements_cmd not in cmd_history:
            ret = subprocess.Popen(requirements_cmd, shell=True, env=plugin_env, cwd=work_dir).wait()
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
                    ret = subprocess.Popen(git_cmd.split(), shell=False, env=plugin_env, cwd=work_dir).wait()
                    if ret != 0:
                        raise Exception('Failed to install git/pip and dependencies with exit code: '+str(ret))
                    else:
                        ret = subprocess.Popen(requirements_cmd, shell=True, env=plugin_env, cwd=work_dir).wait()
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

    if abort.is_set():
        logger.info('plugin aborting...')
        return False
    # env = os.environ.copy()
    if type(args) is str:
        args = args.split()
    if not args:
        args = []
    # Convert them all to strings
    args = [str(x) for x in args if str(x) != '']
    logger.info('%s task started.', name)
    unrecognized_output = []
    # env['PYTHONPATH'] = os.pathsep.join(
    #     ['.', work_dir, env.get('PYTHONPATH', '')] + sys.path)

    args = ' '.join(args)
    logger.info('Task subprocess args: %s', args)

    # set system/version dependent "start_new_session" analogs
    # https://docs.python.org/2/library/subprocess.html#converting-argument-sequence
    kwargs = {}
    if sys.platform != "win32":
        kwargs.update(preexec_fn=os.setsid)

    process = subprocess.Popen(args, bufsize=0, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
              shell=True, universal_newlines=True, env=plugin_env, cwd=work_dir, **kwargs)

    # Poll process for new output until finished
    while True:
        nextline = process.stdout.readline()
        if nextline == '' and process.poll() is not None:
            break
        sys.stdout.write(nextline)
        sys.stdout.flush()
        if abort.is_set():
            logger.info('plugin aborting...')
            p = psutil.Process(process.pid)
            for proc in p.children(recursive=True):
                proc.kill()
            p.kill()
            logger.info('plugin process is killed.')
            return False

    output = process.communicate()[0]
    exitCode = process.returncode

    if (exitCode == 0):
        return output
    else:
        logger.info('Error occured during terminating a process.\ncommand: %s\n exit code: %s\n output:%s\n', str(command), str(exitCode), str(output))

print('======>> Connection Token: '+opt.token + ' <<======')
async def on_shutdown(app):
    print('shutting down...')
    for sid in plugin_sids:
        try:
            await on_kill_plugin(sid, {"id":plugin_sids[sid]['id']})
        finally:
            pass
    print('Plugin engine exited!')
app.on_shutdown.append(on_shutdown)
web.run_app(app, host=opt.host, port=opt.port)
