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
from aiohttp import web, hdrs
from aiohttp import WSCloseCode
from aiohttp import streamer
from urllib.parse import urlparse
from mimetypes import MimeTypes

try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

# add executable path to PATH
os.environ['PATH'] = os.path.split(sys.executable)[0]  + os.pathsep +  os.environ.get('PATH', '')


try:
    subprocess.call(["conda", "-V"])
except OSError as e:
    CONDA_AVAILABLE = False
    if sys.version_info < (3, 0):
        sys.exit('Sorry, ImJoy plugin engine can only run within a conda environment or at least in Python 3.')
    print('WARNING: you are running ImJoy without conda, you may have problem with some plugins.')
else:
    CONDA_AVAILABLE = True

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
parser.add_argument('--force_quit_timeout', type=int, default=5, help='the time (in second) for waiting before kill a plugin process, default: 5 s')
parser.add_argument('--workspace', type=str, default='~/ImJoyWorkspace', help='workspace folder for plugins')
parser.add_argument('--freeze', action="store_true", help='disable conda and pip commands')

opt = parser.parse_args()

if not CONDA_AVAILABLE and not opt.freeze:
    print('WARNING: `pip install` command may not work, in that case you may want to add "--freeze".')

if opt.freeze:
    print('WARNING: you are running the plugin engine with `--freeze`, this means you need to handle all the plugin requirements yourself.')

FORCE_QUIT_TIMEOUT = opt.force_quit_timeout
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
# ALLOWED_ORIGINS = ['http://'+opt.host+':'+opt.port, 'http://imjoy.io', 'https://imjoy.io']
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
        body = '<H1><a href="https://imjoy.io/#/app?token='+params['token']+'">Open ImJoy App</a></H1><p>You may be asked to enter a connection token, use this one:</p><H3>'+params['token'] + '</H3><br>'
    else:
        body = '<H1><a href="https://imjoy.io/#/app">Open ImJoy App</a></H1>'
    body += '<H2>Please use the latest Google Chrome browser to run the ImJoy App.</H2><a href="https://www.google.com/chrome/">Download Chrome</a><p>Note: Safari is not supported due to its restrictions on connecting to localhost. Currently, only FireFox and Chrome (preferred) are supported.</p>'
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
        if not opt.freeze and CONDA_AVAILABLE and env is not None:
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
        else:
            print(f"WARNING: blocked env command: \n{env}\nYou may want to run it yourself.")
            logger.warning(f'env command is blocked because conda is not avaialbe or in `--freeze` mode: {env}')
            env = None

    if type(requirements) is list:
        requirements_pip = " ".join(requirements)
    elif type(requirements) is str:
        requirements_pip = "&& " + requirements
    else:
        raise Exception('wrong requirements type.')

    requirements_cmd = "pip install "+" ".join(default_requirements_py2 if is_py2 else default_requirements_py3) + ' ' + requirements_pip
    if opt.freeze:
        print(f"WARNING: blocked pip command: \n{requirements_cmd}\nYou may want to run it yourself.")
        logger.warning(f'pip command is blocked due to `--freeze` mode: {requirements_cmd}')
        requirements_cmd = None

    if not opt.freeze and CONDA_AVAILABLE:
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
        taskThread = threading.Thread(target=launch_plugin, args=[pid, env, requirements_cmd, f'{cmd} "{template_script}" --id="{pid}" --host={opt.host} --port={opt.port} --secret="{secretKey}" --namespace={NAME_SPACE}', work_dir, abort, pid, plugin_env])
        taskThread.daemon = True
        taskThread.start()
        # execute('python pythonWorkerTemplate.py', './', abort, pid)
        return {'success': True, 'secret': secretKey, 'work_dir': os.path.abspath(work_dir)}
    except Exception as e:
        logger.error(e)
        return {'success': False}

async def force_kill_timeout(t, obj):
    pid = obj['pid']
    for i in range(int(t*10)):
        if obj['force_kill']:
            await asyncio.sleep(0.1)
        else:
            return
    try:
        logger.warning('Timeout, force quitting %s', pid)
        plugins[pid]['abort'].set()
        p = psutil.Process(plugins[pid]['process_id'])
        for proc in p.children(recursive=True):
            proc.kill()
        p.kill()
    except Exception as e:
        logger.error(e)
    finally:
        return

@sio.on('kill_plugin', namespace=NAME_SPACE)
async def on_kill_plugin(sid, kwargs):
    pid = kwargs['id']
    timeout_kill = None
    if pid in plugins:
        print('Killing plugin ', pid)
        obj = {'force_kill': True, 'pid': pid}
        def exited(result):
            obj['force_kill'] = False
            logger.info('Plugin %s exited normally.', pid)
            # kill the plugin now
            plugins[pid]['abort'].set()
            p = psutil.Process(plugins[pid]['process_id'])
            for proc in p.children(recursive=True):
                proc.kill()
            p.kill()
        await sio.emit('to_plugin_'+plugins[pid]['secret'], {'type': 'disconnect'}, callback=exited)
        await force_kill_timeout(FORCE_QUIT_TIMEOUT, obj)
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
        return {'success': False, 'error': 'client has not been registered.'}
    path = kwargs.get('path', '~')
    type = kwargs.get('type', None)
    recursive = kwargs.get('recursive', False)
    files_list = {'success': True}
    path = os.path.normpath(os.path.expanduser(path))
    files_list['path'] = path
    files_list['name'] = os.path.basename(os.path.abspath(path))
    files_list['type'] = 'dir'

    files_list['children'] = scandir(files_list['path'], type, recursive)
    return files_list

generatedUrls = {}
generatedUrlFiles = {}
@streamer
async def file_sender(writer, file_path=None):
    """
    This function will read large file chunk by chunk and send it through HTTP
    without reading them into memory
    """
    with open(file_path, 'rb') as f:
        chunk = f.read(2 ** 16)
        while chunk:
            await writer.write(chunk)
            chunk = f.read(2 ** 16)

async def download_file(request):
    # origin = request.headers.get(hdrs.ORIGIN)
    # if origin is None:
    #     # Terminate CORS according to CORS 6.2.1.
    #     raise web.HTTPForbidden(
    #         text="CORS preflight request failed: "
    #              "origin header is not specified in the request")
    urlid = request.match_info['urlid']  # Could be a HUGE file
    if urlid not in generatedUrls:
        raise web.HTTPForbidden(
            text="Invalid URL")
    fileInfo = generatedUrls[urlid]
    name = request.rel_url.query.get('name', None)
    if fileInfo.get('password', False):
        password = request.rel_url.query.get('password', None)
        if password != fileInfo['password']:
            raise web.HTTPForbidden(text="Incorrect password for accessing this file.")
    headers = fileInfo.get('headers', None)
    default_headers = {'Access-Control-Allow-Origin': '*',
                       'Access-Control-Allow-Headers': 'origin',
                       'Access-Control-Allow-Methods': 'GET'
                      }
    if fileInfo['type'] == 'dir':
        dirname = os.path.dirname(name)
        # list the folder
        if dirname == '' or dirname is None:
            if name != fileInfo['name']:
                raise web.HTTPForbidden(text="File name does not match server record!")
            folder_path = fileInfo['path']
            if not os.path.exists(folder_path):
                return web.Response(
                    body='Folder <{folder_path}> does not exist'.format(folder_path=folder_path),
                    status=404
                )
            else:
                file_list = scandir(folder_path, 'file', False)
                headers = headers or {'Content-Disposition': 'inline; filename="{filename}"'.format(filename=name)}
                headers.update(default_headers)
                return web.json_response(file_list, headers=headers)
        # list the subfolder or get a file in the folder
        else:
            file_path = os.path.join(fileInfo['path'], os.sep.join(name.split('/')[1:]))
            if not os.path.exists(file_path):
                return web.Response(
                    body='File <{file_path}> does not exist'.format(file_path=file_path),
                    status=404
                )
            if os.path.isdir(file_path):
                _, folder_name = os.path.split(file_path)
                file_list = scandir(file_path, 'file', False)
                headers = headers or {'Content-Disposition': 'inline; filename="{filename}"'.format(filename=folder_name)}
                headers.update(default_headers)
                return web.json_response(file_list, headers=headers)
            else:
                _, file_name = os.path.split(file_path)
                mime_type = MimeTypes().guess_type(file_name)[0] or 'application/octet-stream'
                headers = headers or {'Content-Disposition': 'inline; filename="{filename}"'.format(filename=file_name), 'Content-Type': mime_type}
                headers.update(default_headers)
                return web.Response(
                    body=file_sender(file_path=file_path),
                    headers= headers
                )
    elif fileInfo['type'] == 'file':
        file_path = fileInfo['path']
        if name != fileInfo['name']:
            raise web.HTTPForbidden(text="File name does not match server record!")
        file_name = fileInfo['name']
        if not os.path.exists(file_path):
            return web.Response(
                body='File <{file_name}> does not exist'.format(file_name=file_path),
                status=404
            )
        mime_type = MimeTypes().guess_type(file_name)[0] or 'application/octet-stream'
        headers = headers or {'Content-Disposition': 'inline; filename="{filename}"'.format(filename=file_name), 'Content-Type': mime_type}
        headers.update(default_headers)
        return web.Response(
            body=file_sender(file_path=file_path),
            headers=headers
        )
    else:
        raise web.HTTPForbidden(text='Unsupported file type: '+ fileInfo['type'])

app.router.add_get('/file/{urlid}', download_file)

@sio.on('get_file_url', namespace=NAME_SPACE)
async def on_get_file_url(sid, kwargs):
    logger.info("generating file url: %s", kwargs)
    if sid not in clients_sids:
        logger.debug('client %s is not registered.', sid)
        return {'success': False, 'error': 'client has not been registered'}

    path = os.path.abspath(os.path.expanduser(kwargs['path']))
    if not os.path.exists(path):
        return {'success': False, 'error': 'file does not exist.'}
    fileInfo = {'path': path}
    if os.path.isdir(path):
        fileInfo['type'] = 'dir'
    else:
        fileInfo['type'] = 'file'
    if kwargs.get('headers', None):
        fileInfo['headers'] = kwargs['headers']
    _, name = os.path.split(path)
    fileInfo['name'] = name

    if path in generatedUrlFiles:
        return {'success': True, 'url': generatedUrlFiles[path]}
    else:
        urlid = str(uuid.uuid4())
        generatedUrls[urlid] = fileInfo
        generatedUrlFiles[path] = f'http://{opt.host}:{opt.port}/file/{urlid}?name={name}'
        if kwargs.get('password', None):
            fileInfo['password'] = kwargs['password']
            generatedUrlFiles[path] += ('&password=' + fileInfo['password'])
        return {'success': True, 'url': generatedUrlFiles[path]}


@sio.on('get_file_path', namespace=NAME_SPACE)
async def on_get_file_path(sid, kwargs):
    logger.info("generating file url: %s", kwargs)
    if sid not in clients_sids:
        logger.debug('client %s is not registered.', sid)
        return {'success': False, 'error': 'client has not been registered'}

    url = kwargs['url']
    urlid = urlparse(url).path.replace('/file/', '')
    if urlid in generatedUrls:
        fileInfo = generatedUrls[urlid]
        return {'success': True, 'path': fileInfo['path']}
    else:
        return {'success': False, 'error': 'url not found.' }

@sio.on('message', namespace=NAME_SPACE)
async def on_message(sid, kwargs):
    logger.info("message recieved: %s", kwargs)

@sio.on('disconnect', namespace=NAME_SPACE)
async def disconnect(sid):
    tasks = []
    if sid in clients_sids:
        cid = clients_sids[sid]
        del clients_sids[sid]
        if cid in clients and sid in clients[cid]:
            clients[cid].remove(sid)
        if cid in clients or len(clients[cid])==0:
            if cid in plugin_cids:
                for plugin in plugin_cids[cid]:
                    tasks.append(on_kill_plugin(sid, plugin))
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
                tasks.append(on_kill_plugin(sid, exist))
    asyncio.gather(*tasks)
    logger.info('disconnect %s', sid)

def launch_plugin(pid, env, requirements_cmd, args, work_dir, abort, name, plugin_env):
    if abort.is_set():
        logger.info('plugin aborting...')
        return False
    try:
        if env is not None and env != '':
            logger.info('creating environment: %s', env)
            if env not in cmd_history:
                process = subprocess.Popen(env.split(), shell=False, env=plugin_env, cwd=work_dir)
                plugins[pid]['process_id'] = process.pid
                process.wait()
                cmd_history.append(env)
            else:
                logger.debug('skip command: %s', env)

            if abort.is_set():
                logger.info('plugin aborting...')
                return False

        logger.info('installing requirements: %s', requirements_cmd)
        if requirements_cmd is not None and requirements_cmd not in cmd_history:
            process = subprocess.Popen(requirements_cmd, shell=True, env=plugin_env, cwd=work_dir)
            plugins[pid]['process_id'] = process.pid
            ret = process.wait()
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
                    process = subprocess.Popen(git_cmd.split(), shell=False, env=plugin_env, cwd=work_dir)
                    plugins[pid]['process_id'] = process.pid
                    ret = process.wait()
                    if ret != 0:
                        raise Exception('Failed to install git/pip and dependencies with exit code: '+str(ret))
                    else:
                        process = subprocess.Popen(requirements_cmd, shell=True, env=plugin_env, cwd=work_dir)
                        plugins[pid]['process_id'] = process.pid
                        ret = process.wait()
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
    plugins[pid]['process_id'] = process.pid
    # Poll process for new output until finished
    while True:
        out = process.stdout.read(1)
        if out == '' and process.poll() != None:
            break
        if out != '':
            print(out, flush=True)
        if abort.is_set():
            break

    try:
        logger.info('Plugin aborting...')
        p = psutil.Process(process.pid)
        for proc in p.children(recursive=True):
            proc.kill()
        p.kill()
        logger.info('plugin process is killed.')
        output = process.communicate()[0]
        exitCode = process.returncode
    except Exception as e:
        exitCode = 100
    finally:
        if (exitCode == 0):
            return True
        else:
            logger.info('Error occured during terminating a process.\ncommand: %s\n exit code: %s\n output:%s\n', str(args), str(exitCode))
            return False


print('======>> Connection Token: '+opt.token + ' <<======')
async def on_shutdown(app):
    print('Shutting down...')
    logger.info('Shutting down the plugin engine...')
    stopped = threading.Event()
    def loop(): # executed in another thread
        for i in range(10):
            print("Exiting: " + str(10 - i), flush=True)
            time.sleep(1)
            if stopped.is_set():
                break
        print("Force shutting down now!", flush=True)
        logger.debug('Plugin engine is killed.')
        cp = psutil.Process(os.getpid())
        for proc in cp.children(recursive=True):
            proc.kill()
        cp.kill()
        # os._exit(1)
    t = threading.Thread(target=loop)
    t.daemon = True # stop if the program exits
    t.start()

    print('Shutting down the plugins...', flush=True)
    tasks = []
    for sid in plugin_sids:
        try:
            tasks.append(on_kill_plugin(sid, {"id":plugin_sids[sid]['id']}))
        finally:
            pass
    asyncio.gather(*tasks)
    stopped.set()
    logger.info('Plugin engine exited.')

app.on_shutdown.append(on_shutdown)
web.run_app(app, host=opt.host, port=opt.port)
