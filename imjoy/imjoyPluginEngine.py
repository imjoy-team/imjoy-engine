"""Implement the ImJoy plugin engine."""

import argparse
import asyncio
import datetime
import fcntl
import json
import logging
import os
import pathlib
import platform
import pty
import select
import shlex
import shutil
import string
import struct
import subprocess
import sys
import termios
import threading
import time
import traceback
import uuid
from importlib import import_module
from mimetypes import MimeTypes
from urllib.parse import urlparse

import aiohttp_cors
import socketio
import yaml

# import webbrowser
from aiohttp import streamer, web

if sys.platform == "win32":
    from ctypes import windll

    def get_drives():
        """Return windows drives."""
        drives = []
        bitmask = windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drives.append(os.path.abspath(letter + ":/"))
            bitmask >>= 1
        return drives


# read version information from file
HERE = pathlib.Path(__file__).parent
version_info = json.loads((HERE / "VERSION").read_text())

__version__ = version_info["version"]
API_VERSION = version_info["api_version"]

CONDA_AVAILABLE = False
MAX_ATTEMPTS = 1000
NAME_SPACE = "/"

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("ImJoyPluginEngine")

# add executable path to PATH
os.environ["PATH"] = (
    os.path.split(sys.executable)[0] + os.pathsep + os.environ.get("PATH", "")
)


try:
    process = subprocess.Popen(
        ["conda", "info", "--json", "-s"], stdout=subprocess.PIPE
    )
    cout, err = process.communicate()
    conda_prefix = json.loads(cout.decode("ascii"))["conda_prefix"]
    logger.info("Found conda environment: %s", conda_prefix)
    # for fixing CondaHTTPError:
    # https://github.com/conda/conda/issues/6064#issuecomment-458389796
    if os.name == "nt":
        os.environ["PATH"] = (
            os.path.join(conda_prefix, "Library", "bin")
            + os.pathsep
            + os.environ["PATH"]
        )
    CONDA_AVAILABLE = True
except OSError:
    conda_prefix = None
    if sys.version_info < (3, 0):
        sys.exit(
            "Sorry, ImJoy plugin engine can only run within a conda environment "
            "or at least in Python 3."
        )
    print(
        "WARNING: you are running ImJoy without conda, "
        "you may have problem with some plugins."
    )

parser = argparse.ArgumentParser()
parser.add_argument("--token", type=str, default=None, help="connection token")
parser.add_argument("--debug", action="store_true", help="debug mode")
parser.add_argument(
    "--serve", action="store_true", help="download ImJoy web app and serve it locally"
)
parser.add_argument("--host", type=str, default="127.0.0.1", help="socketio host")
parser.add_argument(
    "--base_url",
    type=str,
    default=None,
    help="the base url for accessing this plugin engine",
)
parser.add_argument("--port", type=str, default="9527", help="socketio port")
parser.add_argument(
    "--force_quit_timeout",
    type=int,
    default=5,
    help="the time (in second) for waiting before kill a plugin process, default: 5 s",
)
parser.add_argument(
    "--workspace",
    type=str,
    default="~/ImJoyWorkspace",
    help="workspace folder for plugins",
)
parser.add_argument(
    "--freeze", action="store_true", help="disable conda and pip commands"
)
parser.add_argument(
    "--engine_container_token",
    type=str,
    default=None,
    help="A token set by the engine container which launches the engine",
)

opt = parser.parse_args()

if opt.base_url is None or opt.base_url == "":
    opt.base_url = "http://{}:{}".format(opt.host, opt.port)

if opt.base_url.endswith("/"):
    opt.base_url = opt.base_url[:-1]

if not CONDA_AVAILABLE and not opt.freeze:
    print(
        "WARNING: `pip install` command may not work, "
        "in that case you may want to add `--freeze`."
    )

if opt.freeze:
    print(
        "WARNING: you are running the plugin engine with `--freeze`, "
        "this means you need to handle all the plugin requirements yourself."
    )

FORCE_QUIT_TIMEOUT = opt.force_quit_timeout
WORKSPACE_DIR = os.path.expanduser(opt.workspace)
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

# read token from file if exists
try:
    if opt.token is None or opt.token == "":
        with open(os.path.join(WORKSPACE_DIR, ".token"), "r") as f:
            opt.token = f.read()
except Exception:
    logger.debug("Failed to read token from file")

try:
    if opt.token is None or opt.token == "":
        opt.token = str(uuid.uuid4())
        with open(os.path.join(WORKSPACE_DIR, ".token"), "w") as f:
            f.write(opt.token)
except Exception as e:
    logger.error("Failed to save .token file: %s", str(e))


def get_psutil():
    """Try to import and return psutil."""
    try:
        return import_module("psutil")
    except ImportError:
        print(
            "WARNING: a library called 'psutil' can not be imported, "
            "this may cause problem when killing processes."
        )
        return None


def killProcess(pid):
    """Kill process."""
    psutil = get_psutil()
    if psutil is None:
        return
    try:
        cp = psutil.Process(pid)
        for proc in cp.children(recursive=True):
            try:
                if proc.is_running():
                    proc.kill()
            except psutil.NoSuchProcess:
                logger.info("subprocess %s has already been killed", pid)
            except Exception as e:
                logger.error(
                    "WARNING: failed to kill a subprocess (PID={}). Error: {}".format(
                        pid, str(e)
                    )
                )
        cp.kill()
        logger.info("plugin process %s was killed.", pid)
    except psutil.NoSuchProcess:
        logger.info("process %s has already been killed", pid)
    except Exception as e:
        logger.error(
            "WARNING: failed to kill a process (PID={}), "
            "you may want to kill it manually. Error: {}".format(pid, str(e))
        )


# try to kill last process
pid_file = os.path.join(WORKSPACE_DIR, ".pid")
try:
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            killProcess(int(f.read()))
except Exception:
    logger.debug("Failed to kill last process")
try:
    engine_pid = str(os.getpid())
    with open(pid_file, "w") as f:
        f.write(engine_pid)
except Exception as e:
    logger.error("Failed to save .pid file: %s", str(e))

WEB_APP_DIR = os.path.join(WORKSPACE_DIR, "__ImJoy__")
if opt.serve:
    if shutil.which("git") is None:
        print("Installing git...")
        ret = subprocess.Popen(
            "conda install -y git && git clone -b gh-pages --depth 1 "
            "https://github.com/oeway/ImJoy".split(),
            shell=False,
        ).wait()
        if ret != 0:
            print(
                "Failed to install git, please check whether you have internet access."
            )
            sys.exit(3)
    if os.path.exists(WEB_APP_DIR) and os.path.isdir(WEB_APP_DIR):
        ret = subprocess.Popen(["git", "stash"], cwd=WEB_APP_DIR, shell=False).wait()
        if ret != 0:
            print("Failed to clean files locally.")
        ret = subprocess.Popen(
            ["git", "pull", "--all"], cwd=WEB_APP_DIR, shell=False
        ).wait()
        if ret != 0:
            print("Failed to pull files for serving offline.")
        ret = subprocess.Popen(
            ["git", "checkout", "gh-pages"], cwd=WEB_APP_DIR, shell=False
        ).wait()
        if ret != 0:
            print("Failed to checkout files from gh-pages.")
    if not os.path.exists(WEB_APP_DIR):
        print("Downloading files for serving ImJoy locally...")
        ret = subprocess.Popen(
            "git clone -b gh-pages --depth 1 "
            "https://github.com/oeway/ImJoy __ImJoy__".split(),
            shell=False,
            cwd=WORKSPACE_DIR,
        ).wait()
        if ret != 0:
            print(
                "Failed to download files, "
                "please check whether you have internet access."
            )
            sys.exit(4)

# ALLOWED_ORIGINS = [opt.base_url, 'http://imjoy.io', 'https://imjoy.io']
sio = socketio.AsyncServer()
app = web.Application()
sio.attach(app)

if opt.debug:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.ERROR)

if opt.serve and os.path.exists(os.path.join(WEB_APP_DIR, "index.html")):

    async def index(request):
        """Serve the client-side application."""
        with open(os.path.join(WEB_APP_DIR, "index.html"), "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")

    app.router.add_static("/static", path=str(os.path.join(WEB_APP_DIR, "static")))
    # app.router.add_static('/docs/', path=str(os.path.join(WEB_APP_DIR, 'docs')))

    async def docs_handler(request):
        """Handle docs."""
        raise web.HTTPFound(location="https://imjoy.io/docs")

    app.router.add_get("/docs", docs_handler, name="docs")
    print("A local version of Imjoy web app is available at " + opt.base_url)
else:

    async def index(request):
        """Return index."""
        return web.Response(
            body=(
                '<H1><a href="https://imjoy.io">ImJoy.IO</a></H1><p>'
                'You can run "python -m imjoy --serve" '
                "to serve ImJoy web app locally.</p>"
            ),
            content_type="text/html",
        )


app.router.add_get("/", index)


async def about(request):
    """Return about text."""
    params = request.rel_url.query
    if "token" in params:
        body = (
            "<H1>ImJoy Plugin Engine connection token: </H1><H3>"
            + params["token"]
            + "</H3><br>"
        )
        body += (
            "<p>You have to specify this token when you connect the ImJoy web app "
            "to this Plugin Engine. The token will be saved and automatically reused "
            "when you launch the App again. </p>"
        )
        body += "<br>"
        body += (
            "<p>Alternatively, you can launch a new ImJoy instance "
            "with the link below: </p>"
        )

        if opt.serve:
            body += (
                '<p><a href="'
                + opt.base_url
                + "/#/app?token="
                + params["token"]
                + '">Open ImJoy App</a></p>'
            )
        else:
            body += (
                '<p><a href="https://imjoy.io/#/app?token='
                + params["token"]
                + '">Open ImJoy App</a></p>'
            )

    else:
        if opt.serve:
            body = '<H1><a href="' + opt.base_url + '/#/app">Open ImJoy App</a></H1>'
        else:
            body = '<H1><a href="https://imjoy.io/#/app">Open ImJoy App</a></H1>'
    body += (
        "<H2>Please use the latest Google Chrome browser to run the ImJoy App."
        '</H2><a href="https://www.google.com/chrome/">Download Chrome</a><p>'
        "Note: Safari is not supported "
        "due to its restrictions on connecting to localhost. "
        "Currently, only FireFox and Chrome (preferred) are supported.</p>"
    )
    return web.Response(body=body, content_type="text/html")


app.router.add_get("/about", about)

attempt_count = 0
cmd_history = []
plugins = {}
plugin_sessions = {}
plugin_sids = {}
plugin_signatures = {}
clients = {}
client_sessions = {}
registered_sessions = {}
generatedUrls = {}
generatedUrlFiles = {}
requestUploadFiles = {}
requestUrls = {}
terminal_session = {}

DEFAULT_REQUIREMENTS_PY2 = ["requests", "six", "websocket-client", "numpy"]
DEFAULT_REQUIREMENTS_PY3 = [*DEFAULT_REQUIREMENTS_PY2, "janus"]

REQ_PSUTIL = ["psutil"]
REQ_PSUTIL_CONDA = ["conda:psutil"]

script_dir = os.path.dirname(os.path.normpath(__file__))
template_script = os.path.abspath(os.path.join(script_dir, "imjoyWorkerTemplate.py"))

if CONDA_AVAILABLE:
    if sys.platform == "linux" or sys.platform == "linux2":
        # linux
        conda_activate = "/bin/bash -c 'source " + conda_prefix + "/bin/activate {}'"
    elif sys.platform == "darwin":
        # OS X
        conda_activate = "source activate {}"
    elif sys.platform == "win32":
        # Windows...
        conda_activate = "activate {}"
    else:
        conda_activate = "conda activate {}"
else:
    conda_activate = "{}"


def resumePluginSession(pid, session_id, plugin_signature):
    """Resume plugin session."""
    if pid in plugins:
        if session_id in plugin_sessions:
            plugin_sessions[session_id].append(plugins[pid])
        else:
            plugin_sessions[session_id] = [plugins[pid]]

    if plugin_signature in plugin_signatures:
        plugin_info = plugin_signatures[plugin_signature]
        logger.info("resuming plugin %s", pid)
        return plugin_info
    else:
        return None


def addClientSession(session_id, client_id, sid, base_url, workspace):
    """Add client session."""
    if client_id in clients:
        clients[client_id].append(sid)
        client_connected = True
    else:
        clients[client_id] = [sid]
        client_connected = False
    logger.info("adding client session %s", sid)
    registered_sessions[sid] = {
        "client": client_id,
        "session": session_id,
        "base_url": base_url,
        "workspace": workspace,
    }
    return client_connected


def disconnectClientSession(sid):
    """Disconnect client session."""
    if sid in registered_sessions:
        logger.info("disconnecting client session %s", sid)
        obj = registered_sessions[sid]
        client_id, session_id = obj["client"], obj["session"]
        del registered_sessions[sid]
        if client_id in clients and sid in clients[client_id]:
            clients[client_id].remove(sid)
            if len(clients[client_id]) == 0:
                del clients[client_id]
        if session_id in plugin_sessions:
            for plugin in plugin_sessions[session_id]:
                if "allow-detach" not in plugin["flags"]:
                    killPlugin(plugin["id"])
            del plugin_sessions[session_id]


def addPlugin(plugin_info, sid=None):
    """Add plugin."""
    pid = plugin_info["id"]
    session_id = plugin_info["session_id"]
    plugin_signatures[plugin_info["signature"]] = plugin_info
    plugins[pid] = plugin_info
    if session_id in plugin_sessions:
        plugin_sessions[session_id].append(plugin_info)
    else:
        plugin_sessions[session_id] = [plugin_info]

    if pid in plugins and sid is not None:
        plugin_sids[sid] = plugin_info
        plugin_info["sid"] = sid


def disconnectPlugin(sid):
    """Disconnect plugin."""
    if sid in plugin_sids:
        logger.info("disconnecting plugin session %s", sid)
        pid = plugin_sids[sid]["id"]
        if pid in plugins:
            logger.info("clean up plugin %s", pid)
            if plugins[pid]["signature"] in plugin_signatures:
                logger.info("clean up plugin signature %s", plugins[pid]["signature"])
                del plugin_signatures[plugins[pid]["signature"]]
            del plugins[pid]
        del plugin_sids[sid]
        for session_id in plugin_sessions.keys():
            exist = False
            for p in plugin_sessions[session_id]:
                if p["id"] == pid:
                    exist = p
            if exist:
                logger.info("clean up plugin session %s", session_id)
                plugin_sessions[session_id].remove(exist)
                killPlugin(exist["id"])


def setPluginPID(plugin_id, pid):
    """Set plugin pid."""
    plugins[plugin_id]["process_id"] = pid


def killPlugin(pid):
    """Kill plugin."""
    if pid in plugins:
        try:
            plugins[pid]["abort"].set()
            plugins[pid]["aborting"] = asyncio.get_event_loop().create_future()
            killProcess(plugins[pid]["process_id"])
            print('INFO: "{}" was killed.'.format(pid))
        except Exception as e:
            print('WARNING: failed to kill plugin "{}".'.format(pid))
            logger.error(str(e))
        if "sid" in plugins[pid]:
            if plugins[pid]["sid"] in plugin_sids:
                del plugin_sids[plugins[pid]["sid"]]

        if plugins[pid]["signature"] in plugin_signatures:
            logger.info(
                "clean up killed plugin signature %s", plugins[pid]["signature"]
            )
            del plugin_signatures[plugins[pid]["signature"]]
        logger.info("clean up killed plugin %s", pid)
        del plugins[pid]


async def killAllPlugins(ssid):
    """Kill all plugins."""
    tasks = []
    for sid in list(plugin_sids.keys()):
        try:
            await on_kill_plugin(ssid, {"id": plugin_sids[sid]["id"]})
        except Exception as e:
            logger.error(str(e))

    return asyncio.gather(*tasks)


def parseRepos(requirements, work_dir):
    """Return a list of repositories from a list of requirements."""
    repos = []
    if type(requirements) is list:
        requirements = [str(r) for r in requirements]
        for r in requirements:
            if ":" in r:
                rs = r.split(":")
                tp, libs = rs[0], ":".join(rs[1:])
                tp, libs = tp.strip(), libs.strip()
                libs = [l.strip() for l in libs.split(" ") if l.strip() != ""]
                if tp == "repo" and len(libs) > 0:
                    name = libs[0].split("/")[-1].replace(".git", "")
                    repo = {
                        "url": libs[0],
                        "repo_dir": os.path.join(
                            work_dir, libs[1] if len(libs) > 1 else name
                        ),
                    }
                    repos.append(repo)
    return repos


def parseRequirements(requirements, default_command=None):
    """Parse requirements."""
    if default_command is None:
        default_command = ""
    requirements_cmd = ""
    if type(requirements) is list:
        requirements = [str(r) for r in requirements]

        for r in requirements:
            if ":" in r:
                rs = r.split(":")
                tp, libs = rs[0], ":".join(rs[1:])
                tp, libs = tp.strip(), libs.strip()
                libs = [l.strip() for l in libs.split(" ") if l.strip() != ""]
                if tp == "conda" and len(libs) > 0 and CONDA_AVAILABLE:
                    requirements_cmd += " && conda install -y " + " ".join(libs)
                elif tp == "pip" and len(libs) > 0:
                    requirements_cmd += " && pip install " + " ".join(libs)
                elif tp == "repo" and len(libs) > 0:
                    pass
                elif tp == "cmd" and len(libs) > 0:
                    requirements_cmd += " && " + " ".join(libs)
                elif "+" in tp or "http" in tp:
                    requirements_cmd += " && pip install " + r
                else:
                    raise Exception("Unsupported requirement type: " + tp)
            else:
                requirements_cmd += " && pip install " + r

    elif type(requirements) is str and requirements.strip() != "":
        requirements_cmd += " && " + requirements
    elif (
        requirements is None or type(requirements) is str and requirements.strip() == ""
    ):
        pass
    else:
        raise Exception("Unsupported requirements type.")
    requirements_cmd = "{} && {}".format(requirements_cmd, default_command)
    requirements_cmd = requirements_cmd.strip(" &")
    return requirements_cmd


def console_to_str(s):
    """From pypa/pip project, pip.backwardwardcompat. License MIT."""
    try:
        return s.decode(sys.__stdout__.encoding)
    except UnicodeDecodeError:
        return s.decode("utf_8")
    except AttributeError:  # for tests, #13
        return s


def runCmd(
    cmd,
    shell=False,
    cwd=None,
    log_in_real_time=True,
    check_returncode=True,
    callback=None,
    plugin_id=None,
):
    """Run command.

    From https://github.com/vcs-python/libvcs/.
    """
    proc = subprocess.Popen(
        cmd,
        shell=shell,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        creationflags=0,
        bufsize=1,
        cwd=cwd,
    )
    if plugin_id is not None:
        setPluginPID(plugin_id, proc.pid)

    all_output = []
    code = None
    line = None
    while code is None:
        code = proc.poll()
        if callback and callable(callback):
            line = console_to_str(proc.stderr.read(128))
            if line:
                callback(output=line, timestamp=datetime.datetime.now())
    if callback and callable(callback):
        callback(output="\r", timestamp=datetime.datetime.now())

    lines = filter(None, (line.strip() for line in proc.stdout.readlines()))
    all_output = console_to_str(b"\n".join(lines))
    if code:
        stderr_lines = filter(None, (line.strip() for line in proc.stderr.readlines()))
        all_output = console_to_str(b"".join(stderr_lines))
    output = "".join(all_output)
    if code != 0 and check_returncode:
        raise Exception("Command failed with code {}: {}".format(code, cmd))
    return output


def parseEnv(env, work_dir, default_env_name):
    """Parse environment."""
    env_name = ""
    is_py2 = False
    envs = None

    if type(env) is str:
        env = None if env.strip() == "" else env

    if env is not None:
        if not opt.freeze and CONDA_AVAILABLE:
            if type(env) is str:
                envs = [env]
            else:
                envs = env
            for i, env in enumerate(envs):
                if "conda create" in env:
                    # if not env.startswith('conda'):
                    #     raise Exception('env command must start with conda')
                    if "python=2" in env:
                        is_py2 = True
                    parms = shlex.split(env)
                    if "-n" in parms:
                        env_name = parms[parms.index("-n") + 1]
                    elif "--name" in parms:
                        env_name = parms[parms.index("--name") + 1]
                    else:
                        env_name = default_env_name
                        envs[i] = env.replace(
                            "conda create", "conda create -n " + env_name
                        )

                    if "-y" not in parms:
                        envs[i] = env.replace("conda create", "conda create -y")

                if "conda env create" in env:
                    parms = shlex.split(env)
                    if "-f" in parms:
                        try:
                            env_file = os.path.join(
                                work_dir, parms[parms.index("-f") + 1]
                            )
                            with open(env_file, "r") as stream:
                                env_config = yaml.load(stream)
                                assert "name" in env_config
                                env_name = env_config["name"]
                        except Exception as e:
                            raise Exception(
                                "Failed to read the env name "
                                "from the specified env file: " + str(e)
                            )

                    else:
                        raise Exception(
                            "You should provided a environment file "
                            "via the `conda env create -f`"
                        )

        else:
            print(
                "WARNING: blocked env command: \n{}\n"
                "You may want to run it yourself.".format(env)
            )
            logger.warning(
                "env command is blocked because conda is not available "
                "or in `--freeze` mode: %s",
                env,
            )

    if env_name.strip() == "":
        env_name = None

    return env_name, envs, is_py2


@sio.on("connect", namespace=NAME_SPACE)
def connect(sid, environ):
    """Connect client."""
    logger.info("connect %s", sid)


async def read_and_forward_terminal_output():
    """ read from ternial and forward to the client
    """
    max_read_bytes = 1024 * 20
    while True:
        await asyncio.sleep(0.01)
        if "fd" in terminal_session:
            timeout_sec = 0
            (data_ready, _, _) = select.select(
                [terminal_session["fd"]], [], [], timeout_sec
            )
            if data_ready:
                output = os.read(terminal_session["fd"], max_read_bytes).decode()
                if len(output) > 0:
                    await sio.emit("terminal_output", {"output": output})


@sio.on("start_terminal", namespace=NAME_SPACE)
async def on_start_terminal(sid, kwargs):
    """new terminal client connected"""
    try:
        if sid not in registered_sessions:
            logger.debug("client %s is not registered.", sid)
            return {"success": False, "error": "client not registered."}

        if "child_pid" in terminal_session:
            # already started child process, don't start another
            return {"success": True, "exists": True}
        if sys.platform == "linux" or sys.platform == "linux2":
            # linux
            default_terminal_command = ["bash"]
        elif sys.platform == "darwin":
            # OS X
            default_terminal_command = ["bash"]
        elif sys.platform == "win32":
            # Windows...
            default_terminal_command = ["start", "cmd"]
        else:
            default_terminal_command = ["bash"]
        cmd = kwargs.get("cmd", default_terminal_command)

        # create child process attached to a pty we can read from and write to
        (child_pid, fd) = pty.fork()
        if child_pid == 0:
            # this is the child process fork.
            # anything printed here will show up in the pty, including the output
            # of this subprocess
            subprocess.run(cmd)
        else:
            # this is the parent process fork.
            # store child fd and pid
            terminal_session["fd"] = fd
            terminal_session["child_pid"] = child_pid
            set_winsize(fd, 50, 50)
            cmd = " ".join(shlex.quote(c) for c in cmd)
            print("child pid is", child_pid)
            print(
                f"starting background task with command `{cmd}` to continously read "
                "and forward pty output to client"
            )
            logger.debug("xterm task %s started", terminal_session)
            # os.write(terminal_session["fd"], "\r".encode())
            asyncio.ensure_future(
                read_and_forward_terminal_output(), loop=asyncio.get_event_loop()
            )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@sio.on("terminal_input", namespace=NAME_SPACE)
async def on_terminal_input(sid, data):
    """write to the terminal as if you are typing in a real
    terminal.
    """
    if sid not in registered_sessions:
        return

    if "fd" in terminal_session:
        os.write(terminal_session["fd"], data["input"].encode())


def set_winsize(fd, row, col, xpix=0, ypix=0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


@sio.on("terminal_window_resize", namespace=NAME_SPACE)
async def on_terminal_window_resize(sid, data):
    """resize terminal window"""
    if sid not in registered_sessions:
        return
    if "fd" in terminal_session:
        set_winsize(terminal_session["fd"], data["rows"], data["cols"])


@sio.on("init_plugin", namespace=NAME_SPACE)
async def on_init_plugin(sid, kwargs):
    """Initialize plugin."""
    try:
        if sid in registered_sessions:
            obj = registered_sessions[sid]
            client_id, session_id = obj["client"], obj["session"]
        else:
            logger.debug("client %s is not registered.", sid)
            return {"success": False}
        pid = kwargs["id"]
        config = kwargs.get("config", {})
        env = config.get("env")
        cmd = config.get("cmd", "python")
        pname = config.get("name")
        flags = config.get("flags", [])
        tag = config.get("tag", "")
        requirements = config.get("requirements", []) or []
        workspace = config.get("workspace", "default")
        work_dir = os.path.join(WORKSPACE_DIR, workspace)
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)
        plugin_env = os.environ.copy()
        plugin_env["WORK_DIR"] = work_dir
        logger.info(
            "initialize the plugin. name=%s, id=%s, cmd=%s, workspace=%s",
            pname,
            pid,
            cmd,
            workspace,
        )

        if "single-instance" in flags:
            plugin_signature = "{}/{}".format(pname, tag)
            resume = True
        elif "allow-detach" in flags:
            plugin_signature = "{}/{}/{}/{}".format(client_id, workspace, pname, tag)
            resume = True
        else:
            plugin_signature = None
            resume = False

        if resume:
            plugin_info = resumePluginSession(pid, session_id, plugin_signature)
            if plugin_info is not None:
                if "aborting" in plugin_info:
                    logger.info("Waiting for plugin %s to abort", plugin_info["id"])
                    await plugin_info["aborting"]
                else:
                    logger.debug("plugin already initialized: %s", pid)
                    return {
                        "success": True,
                        "resumed": True,
                        "initialized": True,
                        "secret": plugin_info["secret"],
                        "work_dir": os.path.abspath(work_dir),
                    }
            else:
                logger.info(
                    "failed to resume single instance plugin: %s, %s",
                    pid,
                    plugin_signature,
                )

        secretKey = str(uuid.uuid4())
        abort = threading.Event()
        plugin_info = {
            "secret": secretKey,
            "id": pid,
            "abort": abort,
            "flags": flags,
            "session_id": session_id,
            "name": config["name"],
            "type": config["type"],
            "client_id": client_id,
            "signature": plugin_signature,
        }
        logger.info("Add plugin: %s", str(plugin_info))
        addPlugin(plugin_info)

        @sio.on("from_plugin_" + secretKey, namespace=NAME_SPACE)
        async def message_from_plugin(sid, kwargs):
            # print('forwarding message_'+secretKey, kwargs)
            if kwargs["type"] in [
                "initialized",
                "importSuccess",
                "importFailure",
                "executeSuccess",
                "executeFailure",
            ]:
                await sio.emit("message_from_plugin_" + secretKey, kwargs)
                logger.debug("message from %s", pid)
                if kwargs["type"] == "initialized":
                    addPlugin(plugin_info, sid)
                elif kwargs["type"] == "executeFailure":
                    logger.info("Killing plugin %s due to exeuction failure.", pid)
                    killPlugin(pid)
            else:
                await sio.emit(
                    "message_from_plugin_" + secretKey,
                    {"type": "message", "data": kwargs},
                )

        @sio.on("message_to_plugin_" + secretKey, namespace=NAME_SPACE)
        async def message_to_plugin(sid, kwargs):
            # print('forwarding message_to_plugin_'+secretKey, kwargs)
            if kwargs["type"] == "message":
                await sio.emit("to_plugin_" + secretKey, kwargs["data"])
            logger.debug("message to plugin %s", secretKey)

        eloop = asyncio.get_event_loop()

        def stop_callback(success, message):
            if "aborting" in plugin_info:
                plugin_info["aborting"].set_result(success)
            message = str(message or "")
            logger.info(
                "disconnecting from plugin (success:%s, message: %s)",
                str(success),
                message,
            )
            coro = sio.emit(
                "message_from_plugin_" + secretKey,
                {
                    "type": "disconnected",
                    "details": {"success": success, "message": message},
                },
            )
            asyncio.run_coroutine_threadsafe(coro, eloop).result()

        def logging_callback(msg, type="info"):
            if msg == "":
                return
            coro = sio.emit(
                "message_from_plugin_" + secretKey,
                {"type": "logging", "details": {"value": msg, "type": type}},
            )
            asyncio.run_coroutine_threadsafe(coro, eloop).result()

        args = '{} "{}" --id="{}" --server={} --secret="{}" --namespace={}'.format(
            cmd,
            template_script,
            pid,
            "http://127.0.0.1:" + opt.port,
            secretKey,
            NAME_SPACE,
        )
        taskThread = threading.Thread(
            target=launch_plugin,
            args=[
                stop_callback,
                logging_callback,
                pid,
                pname,
                tag,
                env,
                requirements,
                args,
                work_dir,
                abort,
                pid,
                plugin_env,
            ],
        )
        taskThread.daemon = True
        taskThread.start()
        return {
            "success": True,
            "initialized": False,
            "secret": secretKey,
            "work_dir": os.path.abspath(work_dir),
        }

    except Exception:
        traceback_error = traceback.format_exc()
        print(traceback_error)
        logger.error(traceback_error)
        return {"success": False, "reason": traceback_error}


async def force_kill_timeout(t, obj):
    """Force kill plugin after timeout."""
    pid = obj["pid"]
    for i in range(int(t * 10)):
        if obj["force_kill"]:
            await asyncio.sleep(0.1)
        else:
            return
    try:
        logger.warning("Timeout, force quitting %s", pid)
        killPlugin(pid)
    finally:
        return


@sio.on("reset_engine", namespace=NAME_SPACE)
async def on_reset_engine(sid, kwargs):
    """Reset engine."""
    logger.info("kill plugin: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered"}

    global attempt_count
    global attempt_count
    global cmd_history
    global plugins
    global plugin_sessions
    global plugin_sids
    global plugin_signatures
    # global clients
    # global client_sessions
    # global registered_sessions
    global terminal_session
    global generatedUrls
    global generatedUrlFiles
    global requestUploadFiles
    global requestUrls

    await killAllPlugins(sid)

    attempt_count = 0
    cmd_history = []
    plugins = {}
    plugin_sessions = {}
    plugin_sids = {}
    plugin_signatures = {}
    # clients = {}
    # client_sessions = {}
    # registered_sessions = {}
    terminal_session = {}
    generatedUrls = {}
    generatedUrlFiles = {}
    requestUploadFiles = {}
    requestUrls = {}

    return {"success": True}


@sio.on("kill_plugin", namespace=NAME_SPACE)
async def on_kill_plugin(sid, kwargs):
    """Kill plugin."""
    logger.info("kill plugin: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered"}

    pid = kwargs["id"]
    if pid in plugins:
        if "killing" not in plugins[pid]:
            obj = {"force_kill": True, "pid": pid}
            plugins[pid]["killing"] = True

            def exited(result):
                obj["force_kill"] = False
                logger.info("Plugin %s exited normally.", pid)
                # kill the plugin now
                killPlugin(pid)

            await sio.emit(
                "to_plugin_" + plugins[pid]["secret"],
                {"type": "disconnect"},
                callback=exited,
            )
            await force_kill_timeout(FORCE_QUIT_TIMEOUT, obj)
    return {"success": True}


@sio.on("register_client", namespace=NAME_SPACE)
async def on_register_client(sid, kwargs):
    """Register client."""
    global attempt_count
    client_id = kwargs.get("id", str(uuid.uuid4()))
    workspace = kwargs.get("workspace", "default")
    session_id = kwargs.get("session_id", str(uuid.uuid4()))
    base_url = kwargs.get("base_url", opt.base_url)
    if base_url.endswith("/"):
        base_url = base_url[:-1]

    token = kwargs.get("token")
    if token != opt.token:
        logger.debug("token mismatch: %s != %s", token, opt.token)
        print("======== Connection Token: " + opt.token + " ========")
        if opt.engine_container_token is not None:
            await sio.emit(
                "message_to_container_" + opt.engine_container_token,
                {
                    "type": "popup_token",
                    "client_id": client_id,
                    "session_id": session_id,
                },
            )
        # try:
        #     webbrowser.open(
        #         'http://'+opt.host+':'+opt.port+'/about?token='+opt.token,
        #         new=0, autoraise=True)
        # except Exception as e:
        #     print('Failed to open the browser.')
        attempt_count += 1
        if attempt_count >= MAX_ATTEMPTS:
            logger.info("Client exited because max attemps exceeded: %s", attempt_count)
            sys.exit(100)
        return {"success": False}
    else:
        attempt_count = 0
        if addClientSession(session_id, client_id, sid, base_url, workspace):
            confirmation = True
            message = (
                "Another ImJoy session is connected to this Plugin Engine({}), "
                "allow a new session to connect?".format(base_url)
            )
        else:
            confirmation = False
            message = None

        logger.info("register client: %s", kwargs)

        engine_info = {"api_version": API_VERSION, "version": __version__}
        engine_info["platform"] = {
            "uname": ", ".join(platform.uname()),
            "machine": platform.machine(),
            "system": platform.system(),
            "processor": platform.processor(),
            "node": platform.node(),
        }

        return {
            "success": True,
            "confirmation": confirmation,
            "message": message,
            "engine_info": engine_info,
        }


def scandir(path, type=None, recursive=False):
    """Scan a directory for a type of files return a list of files found."""
    file_list = []
    for f in os.scandir(path):
        if f.name.startswith("."):
            continue
        if type is None or type == "file":
            if os.path.isdir(f.path):
                if recursive:
                    file_list.append(
                        {
                            "name": f.name,
                            "type": "dir",
                            "children": scandir(f.path, type, recursive),
                        }
                    )
                else:
                    file_list.append({"name": f.name, "type": "dir"})
            else:
                file_list.append({"name": f.name, "type": "file"})
        elif type == "directory":
            if os.path.isdir(f.path):
                file_list.append({"name": f.name})
    return file_list


@sio.on("list_dir", namespace=NAME_SPACE)
async def on_list_dir(sid, kwargs):
    """List files in directory."""
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered."}

    try:
        workspace_dir = os.path.join(
            WORKSPACE_DIR, registered_sessions[sid]["workspace"]
        )

        path = kwargs.get("path", workspace_dir)

        if not os.path.isabs(path):
            path = os.path.join(workspace_dir, path)
        path = os.path.normpath(os.path.expanduser(path))

        type = kwargs.get("type")
        recursive = kwargs.get("recursive", False)
        files_list = {"success": True}
        files_list["path"] = path
        files_list["name"] = os.path.basename(os.path.abspath(path))
        files_list["type"] = "dir"
        files_list["children"] = scandir(files_list["path"], type, recursive)

        if sys.platform == "win32" and os.path.abspath(path) == os.path.abspath("/"):
            files_list["drives"] = get_drives()

        return files_list
    except Exception as e:
        print(traceback.format_exc())
        logger.error("list dir error: %s", str(e))
        return {"success": False, "error": str(e)}


@sio.on("remove_files", namespace=NAME_SPACE)
async def on_remove_files(sid, kwargs):
    """Remove files."""
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered."}
    logger.info("removing files: %s", kwargs)
    workspace_dir = os.path.join(WORKSPACE_DIR, registered_sessions[sid]["workspace"])
    path = kwargs.get("path", workspace_dir)
    if not os.path.isabs(path):
        path = os.path.join(workspace_dir, path)
    path = os.path.normpath(os.path.expanduser(path))
    type = kwargs.get("type")
    recursive = kwargs.get("recursive", False)

    if os.path.exists(path) and not os.path.isdir(path) and type == "file":
        try:
            os.remove(path)
            return {"success": True}
        except Exception as e:
            logger.error("remove files error: %s", str(e))
            return {"success": False, "error": str(e)}
    elif os.path.exists(path) and os.path.isdir(path) and type == "dir":
        try:
            if recursive:
                dirname, filename = os.path.split(path)
                shutil.move(path, os.path.join(dirname, "." + filename))
                # shutil.rmtree(path)
            else:
                os.rmdir(path)
            return {"success": True}
        except Exception as e:
            logger.error("remove files error: %s", str(e))
            return {"success": False, "error": str(e)}
    else:
        logger.error("remove files error: %s", "File not exists or type mismatch.")
        return {"success": False, "error": "File not exists or type mismatch."}


@streamer
async def file_sender(writer, file_path=None):
    """Read a large file chunk by chunk and send it through HTTP.

    Do not read the chunks into memory.
    """
    with open(file_path, "rb") as f:
        chunk = f.read(2 ** 16)
        while chunk:
            await writer.write(chunk)
            chunk = f.read(2 ** 16)


@sio.on("request_upload_url", namespace=NAME_SPACE)
async def on_request_upload_url(sid, kwargs):
    """Request upload url."""
    logger.info("requesting file upload url: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered"}

    urlid = str(uuid.uuid4())
    fileInfo = {
        "id": urlid,
        "overwrite": kwargs.get("overwrite", False),
        "workspace": registered_sessions[sid]["workspace"],
    }
    if "path" in kwargs:
        fileInfo["path"] = kwargs["path"]

    if "dir" in kwargs:
        path = os.path.expanduser(kwargs["dir"])
        if not os.path.isabs(path):
            path = os.path.join(WORKSPACE_DIR, fileInfo["workspace"], path)
        fileInfo["dir"] = path

    if "path" in fileInfo:
        path = fileInfo["path"]
        if "dir" in fileInfo:
            path = os.path.join(fileInfo["dir"], path)
        else:
            path = os.path.join(WORKSPACE_DIR, fileInfo["workspace"], path)

        if os.path.exists(path) and not kwargs.get("overwrite", False):
            return {"success": False, "error": "file already exist."}

    base_url = kwargs.get("base_url", registered_sessions[sid]["base_url"])
    url = "{}/upload/{}".format(base_url, urlid)
    requestUrls[url] = fileInfo
    requestUploadFiles[urlid] = fileInfo
    return {"success": True, "id": urlid, "url": url}


async def upload_file(request):
    """Upload file."""
    urlid = request.match_info["urlid"]  # Could be a HUGE file
    if urlid not in requestUploadFiles:
        raise web.HTTPForbidden(text="Invalid URL")

    fileInfo = requestUploadFiles[urlid]
    try:
        reader = await request.multipart()
        field = None
        while True:
            part = await reader.next()
            print(part, part.filename)
            if part.filename is None:
                continue
            field = part
            break
        filename = field.filename
        # You cannot rely on Content-Length if transfer is chunked.
        size = 0
        if "path" in fileInfo:
            path = fileInfo["path"]
        else:
            path = filename

        if "dir" in fileInfo:
            path = os.path.join(fileInfo["dir"], path)
        else:
            path = os.path.join(WORKSPACE_DIR, fileInfo["workspace"], path)

        if os.path.exists(path) and not fileInfo.get("overwrite", False):
            return web.Response(body="File {} already exists.".format(path), status=404)

        logger.info("uploading file to %s", path)
        directory, _ = os.path.split(path)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(path, "wb") as f:
            while True:
                chunk = await field.read_chunk()  # 8192 bytes by default.
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
        fileInfo["size"] = size
        fileInfo["path"] = path
        logger.info("file saved to %s (size %d)", path, size)
        return web.json_response(fileInfo)

    except Exception as e:
        print(traceback.format_exc())
        logger.error("failed to upload file error: %s", str(e))
        return web.Response(
            body="Failed to upload, error: {}".format(str(e)), status=404
        )


cors = aiohttp_cors.setup(
    app,
    defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True, expose_headers="*", allow_headers="*"
        )
    },
)

# app.router.add_post('/upload/{urlid}', upload_file)
cors.add(app.router.add_route("POST", "/upload/{urlid}", upload_file))


async def download_file(request):
    """Download file."""
    urlid = request.match_info["urlid"]  # Could be a HUGE file
    name = request.match_info["name"]
    if urlid not in generatedUrls:
        raise web.HTTPForbidden(text="Invalid URL")
    fileInfo = generatedUrls[urlid]
    if fileInfo.get("password", False):
        password = request.match_info.get("password")
        if password != fileInfo["password"]:
            raise web.HTTPForbidden(text="Incorrect password for accessing this file.")
    headers = fileInfo.get("headers")
    default_headers = {}
    if fileInfo["type"] == "dir":
        dirname = os.path.dirname(name)
        # list the folder
        if dirname == "" or dirname is None:
            if name != fileInfo["name"]:
                raise web.HTTPForbidden(text="File name does not match server record!")
            folder_path = fileInfo["path"]
            if not os.path.exists(folder_path):
                return web.Response(
                    body="Folder <{folder_path}> does not exist".format(
                        folder_path=folder_path
                    ),
                    status=404,
                )
            else:
                file_list = scandir(folder_path, "file", False)
                headers = headers or {
                    "Content-Disposition": 'inline; filename="{filename}"'.format(
                        filename=name
                    )
                }
                headers.update(default_headers)
                return web.json_response(file_list, headers=headers)
        # list the subfolder or get a file in the folder
        else:
            file_path = os.path.join(fileInfo["path"], os.sep.join(name.split("/")[1:]))
            if not os.path.exists(file_path):
                return web.Response(
                    body="File <{file_path}> does not exist".format(
                        file_path=file_path
                    ),
                    status=404,
                )
            if os.path.isdir(file_path):
                _, folder_name = os.path.split(file_path)
                file_list = scandir(file_path, "file", False)
                headers = headers or {
                    "Content-Disposition": 'inline; filename="{filename}"'.format(
                        filename=folder_name
                    )
                }
                headers.update(default_headers)
                return web.json_response(file_list, headers=headers)
            else:
                _, file_name = os.path.split(file_path)
                mime_type = (
                    MimeTypes().guess_type(file_name)[0] or "application/octet-stream"
                )
                file_size = os.path.getsize(file_path)
                headers = headers or {
                    "Content-Disposition": 'inline; filename="{filename}"'.format(
                        filename=file_name
                    ),
                    "Content-Type": mime_type,
                    "Content-Length": str(file_size),
                }
                headers.update(default_headers)
                return web.Response(
                    body=file_sender(file_path=file_path), headers=headers
                )
    elif fileInfo["type"] == "file":
        file_path = fileInfo["path"]
        if name != fileInfo["name"]:
            raise web.HTTPForbidden(text="File name does not match server record!")
        file_name = fileInfo["name"]
        if not os.path.exists(file_path):
            return web.Response(
                body="File <{file_name}> does not exist".format(file_name=file_path),
                status=404,
            )
        mime_type = MimeTypes().guess_type(file_name)[0] or "application/octet-stream"
        file_size = os.path.getsize(file_path)
        headers = headers or {
            "Content-Disposition": 'inline; filename="{filename}"'.format(
                filename=file_name
            ),
            "Content-Type": mime_type,
            "Content-Length": str(file_size),
        }
        headers.update(default_headers)
        return web.Response(body=file_sender(file_path=file_path), headers=headers)
    else:
        raise web.HTTPForbidden(text="Unsupported file type: " + fileInfo["type"])


cors.add(app.router.add_get("/file/{urlid}/{name:.+}", download_file))
cors.add(app.router.add_get("/file/{urlid}@{password}/{name:.+}", download_file))


@sio.on("get_file_url", namespace=NAME_SPACE)
async def on_get_file_url(sid, kwargs):
    """Return file url."""
    logger.info("generating file url: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered"}

    path = os.path.abspath(os.path.expanduser(kwargs["path"]))
    if not os.path.exists(path):
        return {"success": False, "error": "file does not exist."}
    fileInfo = {"path": path}
    if os.path.isdir(path):
        fileInfo["type"] = "dir"
    else:
        fileInfo["type"] = "file"
    if kwargs.get("headers"):
        fileInfo["headers"] = kwargs["headers"]
    _, name = os.path.split(path)
    fileInfo["name"] = name
    if path in generatedUrlFiles:
        return {"success": True, "url": generatedUrlFiles[path]}
    else:
        urlid = str(uuid.uuid4())
        generatedUrls[urlid] = fileInfo
        base_url = kwargs.get("base_url", registered_sessions[sid]["base_url"])
        if kwargs.get("password"):
            fileInfo["password"] = kwargs["password"]
            generatedUrlFiles[path] = "{}/file/{}@{}/{}".format(
                base_url, urlid, fileInfo["password"], name
            )
        else:
            generatedUrlFiles[path] = "{}/file/{}/{}".format(base_url, urlid, name)
        return {"success": True, "url": generatedUrlFiles[path]}


@sio.on("get_file_path", namespace=NAME_SPACE)
async def on_get_file_path(sid, kwargs):
    """Return file path."""
    logger.info("generating file url: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered"}

    url = kwargs["url"]
    urlid = urlparse(url).path.replace("/file/", "")
    if urlid in generatedUrls:
        fileInfo = generatedUrls[urlid]
        return {"success": True, "path": fileInfo["path"]}
    else:
        return {"success": False, "error": "url not found."}


@sio.on("get_engine_status", namespace=NAME_SPACE)
async def on_get_engine_status(sid, kwargs):
    """Return engine status."""
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered."}
    psutil = get_psutil()
    if psutil is None:
        return {"success": False, "error": "psutil is not available."}
    current_process = psutil.Process()
    children = current_process.children(recursive=True)
    pid_dict = {}
    for i in plugins:
        p = plugins[i]
        pid_dict[p["process_id"]] = p
    procs = []
    for proc in children:
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            if proc.pid in pid_dict:
                procs.append({"name": pid_dict[proc.pid]["name"], "pid": proc.pid})
            else:
                procs.append({"name": proc.name(), "pid": proc.pid})
    return {
        "success": True,
        "plugin_num": len(plugins),
        "plugin_processes": procs,
        "engine_process": current_process.pid,
    }


@sio.on("kill_plugin_process", namespace=NAME_SPACE)
async def on_kill_plugin_process(sid, kwargs):
    """Kill plugin process."""
    if sid not in registered_sessions:
        logger.debug("client %s is not registered.", sid)
        return {"success": False, "error": "client has not been registered."}
    if "all" not in kwargs:
        return {
            "success": False,
            "error": 'You must provide the pid of the plugin process or "all=true".',
        }
    if kwargs["all"]:
        logger.info("Killing all the plugins...")
        await killAllPlugins(sid)
        return {"success": True}
    else:
        try:
            print("Killing plugin process (pid=" + str(kwargs["pid"]) + ")...")
            killProcess(int(kwargs["pid"]))
            return {"success": True}
        except Exception:
            return {
                "success": False,
                "error": "Failed to kill plugin process: #" + str(kwargs["pid"]),
            }


@sio.on("message", namespace=NAME_SPACE)
async def on_message(sid, kwargs):
    """Receive message."""
    logger.info("message recieved: %s", kwargs)


@sio.on("disconnect", namespace=NAME_SPACE)
async def disconnect(sid):
    """Disconnect client."""
    disconnectClientSession(sid)
    disconnectPlugin(sid)
    logger.info("disconnect %s", sid)


def launch_plugin(
    stop_callback,
    logging_callback,
    pid,
    pname,
    tag,
    env,
    requirements,
    args,
    work_dir,
    abort,
    name,
    plugin_env,
):
    """Launch plugin."""
    if abort.is_set():
        logger.info("plugin aborting...")
        logging_callback("plugin aborting...")
        return False
    env_name = None
    try:
        repos = parseRepos(requirements, work_dir)
        logging_callback(2, type="progress")
        for k, r in enumerate(repos):
            try:
                print("Cloning repo " + r["url"] + " to " + r["repo_dir"])
                logging_callback("Cloning repo " + r["url"] + " to " + r["repo_dir"])
                if os.path.exists(r["repo_dir"]):
                    assert os.path.isdir(r["repo_dir"])
                    cmd = "git pull --all"
                    runCmd(cmd.split(" "), cwd=r["repo_dir"], plugin_id=pid)
                else:
                    cmd = (
                        "git clone --progress --depth=1 "
                        + r["url"]
                        + " "
                        + r["repo_dir"]
                    )
                    runCmd(cmd.split(" "), cwd=work_dir, plugin_id=pid)
                logging_callback(k * 5, type="progress")
            except Exception as ex:
                logging_callback(
                    "Failed to obtain the git repo: " + str(ex), type="error"
                )

        default_env_name = "{}-{}".format(pname, tag) if tag != "" else pname
        default_env_name = default_env_name.replace(" ", "_")
        env_name, envs, is_py2 = parseEnv(env, work_dir, default_env_name)
        default_requirements = (
            DEFAULT_REQUIREMENTS_PY2 if is_py2 else DEFAULT_REQUIREMENTS_PY3
        )
        default_requirements_cmd = parseRequirements(default_requirements)
        requirements_cmd = parseRequirements(requirements, default_requirements_cmd)

        if envs is not None and len(envs) > 0:
            for env in envs:
                print("Running env command: " + env)
                logger.info("running env command: %s", env)
                if env not in cmd_history:
                    logging_callback("running env command: {}".format(env))
                    code, errors = run_process(
                        pid, env.split(), env=plugin_env, cwd=work_dir
                    )

                    if code == 0:
                        cmd_history.append(env)
                        logging_callback("env command executed successfully.")

                    if errors is not None:
                        logging_callback(str(errors, "utf-8"), type="error")

                    logging_callback(30, type="progress")
                else:
                    logger.debug("skip command: %s", env)
                    logging_callback("skip env command: " + env)

                if abort.is_set():
                    logger.info("plugin aborting...")
                    return False

        if opt.freeze:
            print(
                "WARNING: blocked pip command: \n{}\n"
                "You may want to run it yourself.".format(requirements_cmd)
            )
            logger.warning(
                "pip command is blocked due to `--freeze` mode: %s", requirements_cmd
            )
            requirements_cmd = None

        if not opt.freeze and CONDA_AVAILABLE and env_name is not None:
            requirements_cmd = conda_activate.format(
                env_name + " && " + requirements_cmd
            )

        logger.info("Running requirements command: %s", requirements_cmd)
        print("Running requirements command: ", requirements_cmd)
        if requirements_cmd is not None and requirements_cmd not in cmd_history:
            code, errors = run_process(
                pid, requirements_cmd, shell=True, env=plugin_env, cwd=work_dir
            )
            logging_callback(
                "Running requirements subprocess(pid={}): {}".format(
                    plugins[pid]["process_id"], requirements_cmd
                )
            )
            if code != 0:
                logging_callback(
                    "Failed to run requirements command: {}".format(requirements_cmd),
                    type="error",
                )
                if errors is not None:
                    logging_callback(str(errors, "utf-8"), type="error")
                git_cmd = ""
                if shutil.which("git") is None:
                    git_cmd += " git"
                if shutil.which("pip") is None:
                    git_cmd += " pip"
                if git_cmd != "":
                    logger.info("pip command failed, trying to install git and pip...")
                    # try to install git and pip
                    git_cmd = "conda install -y" + git_cmd
                    code, _ = run_process(
                        pid, git_cmd.split(), stderr=None, env=plugin_env, cwd=work_dir
                    )
                    if code != 0:
                        logging_callback(
                            "Failed to install git/pip and dependencies "
                            "with exit code: " + str(code),
                            type="error",
                        )
                        raise Exception(
                            "Failed to install git/pip and dependencies "
                            "with exit code: " + str(code)
                        )
                    else:
                        code, errors = run_process(
                            pid,
                            requirements_cmd,
                            shell=True,
                            stderr=None,
                            env=plugin_env,
                            cwd=work_dir,
                        )
                        if code != 0:
                            logging_callback(
                                "Failed to install dependencies with exit code: "
                                + str(code),
                                type="error",
                            )
                            raise Exception(
                                "Failed to install dependencies with exit code: "
                                + str(code)
                            )
            else:
                cmd_history.append(requirements_cmd)
                logging_callback("Requirements command executed successfully.")
            logging_callback(70, type="progress")
        else:
            logger.debug("skip command: %s", requirements_cmd)
        if not opt.freeze:
            psutil_cmd = parseRequirements(REQ_PSUTIL)
            code, _ = run_process(
                pid, psutil_cmd, shell=True, stderr=None, env=plugin_env, cwd=work_dir
            )
        if not opt.freeze and code and CONDA_AVAILABLE and env_name is not None:
            psutil_cmd = parseRequirements(REQ_PSUTIL_CONDA)
            psutil_cmd = conda_activate.format("{} && {}".format(env_name, psutil_cmd))
            code, _ = run_process(
                pid, psutil_cmd, shell=True, stderr=None, env=plugin_env, cwd=work_dir
            )

    except Exception as e:
        error_traceback = traceback.format_exc()
        print(error_traceback)
        logger.error(
            "Failed to setup plugin virtual environment or its requirements: %s",
            error_traceback,
        )
        logging_callback(
            "Failed to setup plugin virual environment or its requirements: "
            + error_traceback,
            type="error",
        )
        abort.set()

    if abort.is_set():
        logger.info("Plugin aborting...")
        logging_callback("Plugin aborting...")
        return False
    # env = os.environ.copy()
    if CONDA_AVAILABLE and env_name is not None:
        args = conda_activate.format(env_name + " && " + args)
    if type(args) is str:
        args = args.split()
    if not args:
        args = []
    # Convert them all to strings
    args = [str(x) for x in args if str(x) != ""]
    logger.info("%s task started.", name)

    args = " ".join(args)
    logger.info("Task subprocess args: %s", args)

    # set system/version dependent "start_new_session" analogs
    # https://docs.python.org/2/library/subprocess.html#converting-argument-sequence
    kwargs = {}
    if sys.platform != "win32":
        kwargs.update(preexec_fn=os.setsid)
    logging_callback(100, type="progress")
    try:
        process = subprocess.Popen(
            args,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            env=plugin_env,
            cwd=work_dir,
            **kwargs,
        )
        logging_callback("running subprocess(pid={}) with {}".format(process.pid, args))
        setPluginPID(pid, process.pid)
        # Poll process for new output until finished
        stdfn = sys.stdout.fileno()

        logging_callback(0, type="progress")

        while True:
            out = process.stdout.read(1)
            if out == "" and process.poll() is not None:
                break
            os.write(stdfn, out)
            sys.stdout.flush()
            if abort.is_set() or process.poll() is not None:
                break
            time.sleep(0)

        logger.info("Plugin aborting...")
        killProcess(process.pid)

        outputs, errors = process.communicate()
        if outputs is not None:
            outputs = str(outputs, "utf-8")
        if errors is not None:
            errors = str(errors, "utf-8")
        exitCode = process.returncode
    except Exception as e:
        print(traceback.format_exc())
        outputs, errors = "", str(e)
        exitCode = 100
    finally:
        if exitCode == 0:
            logging_callback("plugin process exited with code {}".format(0))
            stop_callback(True, outputs)
            return True
        else:
            logging_callback(
                "plugin process exited with code {}".format(exitCode), type="error"
            )
            logger.info(
                "Error occured during terminating a process.\n"
                "command: %s\n exit code: %s\n",
                str(args),
                str(exitCode),
            )
            stop_callback(
                False,
                (errors or "")
                + "\nplugin process exited with code {}".format(exitCode),
            )
            return False


def run_process(plugin_id, cmd, **kwargs):
    """Run subprocess command."""
    shell = kwargs.pop("shell", False)
    stderr = kwargs.pop("stderr", subprocess.PIPE)
    process_ = subprocess.Popen(cmd, shell=shell, stderr=stderr, **kwargs)
    setPluginPID(plugin_id, process_.pid)
    return_code = process_.wait()
    if stderr is not None:
        _, errors = process_.communicate()
    else:
        errors = None

    return return_code, errors


async def on_startup(app):
    """Start plugin engine."""
    print("ImJoy Python Plugin Engine (version {})".format(__version__))

    if opt.serve:
        print(
            "You can access your local ImJoy web app through "
            + opt.base_url
            + " , imjoy!"
        )
    else:
        print(
            "Please go to https://imjoy.io/#/app "
            "with your web browser (Chrome or FireFox)"
        )
    print("Connection Token: " + opt.token)
    sys.stdout.flush()


async def on_shutdown(app):
    """Shut down engine."""
    print("Shutting down...")
    logger.info("Shutting down the plugin engine...")
    stopped = threading.Event()

    def loop():  # executed in another thread
        for i in range(5):
            print("Exiting: " + str(5 - i), flush=True)
            time.sleep(0.5)
            if stopped.is_set():
                break
        print("Force shutting down now!", flush=True)
        logger.debug("Plugin engine is killed.")
        killProcess(os.getpid())
        # os._exit(1)

    t = threading.Thread(target=loop)
    t.daemon = True  # stop if the program exits
    t.start()

    print("Shutting down the plugins...", flush=True)
    # stopped.set()
    logger.info("Plugin engine exited.")
    try:
        os.remove(pid_file)
    except Exception:
        logger.info("Failed to remove the pid file.")


app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)


def main():
    """Run app."""
    try:
        web.run_app(app, host=opt.host, port=int(opt.port))
    except OSError as e:
        if e.errno in {48}:
            print(
                "ERROR: Failed to open port {}, "
                "please try to terminate the process which is using that port, "
                "or restart your computer.".format(opt.port)
            )


if __name__ == "__main__":
    main()
