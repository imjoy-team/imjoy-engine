"""Provide a plugin manager."""
import asyncio
import datetime
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import uuid

import GPUtil

from imjoy import __version__, API_VERSION, IMJOY_PACKAGE_DIR
from imjoy.connection.decorator import socketio_handler as sio_on
from imjoy.utils import console_to_str, parse_repos, get_psutil, kill_process
from .helper import (
    apply_conda_activate,
    install_reqs,
    parse_env,
    parse_requirements,
    run_commands,
    run_process,
)

MAX_ATTEMPTS = 1000


def setup_subprocess_runner(engine):
    """Set up the subprocess runner."""
    engine.conn.register_event_handler(on_register_client)
    engine.conn.register_event_handler(on_init_plugin)
    engine.conn.register_event_handler(on_kill_plugin)
    engine.conn.register_event_handler(on_kill_plugin_process)
    engine.conn.register_event_handler(disconnect_client_session)
    engine.conn.register_event_handler(disconnect_plugin)
    engine.conn.register_event_handler(reset_engine_plugins)


@sio_on("init_plugin")
async def on_init_plugin(engine, sid, kwargs):
    """Initialize plugin."""
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    try:
        if sid in registered_sessions:
            obj = registered_sessions[sid]
            client_id, session_id = obj["client"], obj["session"]
        else:
            logger.debug("Client %s is not registered", sid)
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
        work_dir = os.path.join(engine.opt.workspace_dir, workspace)
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)
        plugin_env = os.environ.copy()
        plugin_env["WORK_DIR"] = work_dir
        if engine.opt.dev:
            plugin_env["PYTHONPATH"] = (
                IMJOY_PACKAGE_DIR + os.path.pathsep + plugin_env.get("PYTHONPATH", "")
            )
            worker_module = "workers.python_worker"
            logger.debug(
                "ImJoy package directory was added to PYTHONPATH, will run module `workers.python_worker`."
            )
        else:
            worker_module = "imjoy.workers.python_worker"
            logger.debug(
                "Will run module `imjoy.workers.python_worker` from installed ImJoy package."
            )

        logger.info(
            "Initialize the plugin, name=%s, id=%s, cmd=%s, workspace=%s",
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
            plugin_info = resume_plugin_session(
                engine, pid, session_id, plugin_signature
            )
            if plugin_info is not None:
                if "aborting" in plugin_info:
                    logger.info("Waiting for plugin %s to abort", plugin_info["id"])
                    await plugin_info["aborting"]
                else:
                    logger.debug("Plugin already initialized: %s", pid)
                    return {
                        "success": True,
                        "resumed": True,
                        "initialized": True,
                        "secret": plugin_info["secret"],
                        "work_dir": os.path.abspath(work_dir),
                    }
            else:
                logger.info(
                    "Failed to resume single instance plugin: %s, %s",
                    pid,
                    plugin_signature,
                )

        secret_key = str(uuid.uuid4())
        abort = threading.Event()
        plugin_info = {
            "secret": secret_key,
            "id": pid,
            "abort": abort,
            "flags": flags,
            "session_id": session_id,
            "name": config["name"],
            "type": config["type"],
            "client_id": client_id,
            "signature": plugin_signature,
            "process_id": None,
        }
        logger.debug("Add plugin: %s", plugin_info)
        add_plugin(engine, plugin_info)

        @sio_on("from_plugin_" + secret_key)
        async def message_from_plugin(engine, sid, kwargs):
            if kwargs["type"] in [
                "initialized",
                "importSuccess",
                "importFailure",
                "executeSuccess",
                "executeFailure",
            ]:
                await engine.conn.sio.emit("message_from_plugin_" + secret_key, kwargs)
                logger.debug("Message from %s", pid)
                if kwargs["type"] == "initialized":
                    add_plugin(engine, plugin_info, sid)
                elif kwargs["type"] == "executeFailure":
                    logger.info("Killing plugin %s due to exeuction failure", pid)
                    kill_plugin(engine, pid)
            else:
                await engine.conn.sio.emit(
                    "message_from_plugin_" + secret_key,
                    {"type": "message", "data": kwargs},
                )

        engine.conn.register_event_handler(message_from_plugin)

        @sio_on("message_to_plugin_" + secret_key)
        async def message_to_plugin(engine, _, kwargs):
            if kwargs["type"] == "message":
                await engine.conn.sio.emit("to_plugin_" + secret_key, kwargs["data"])
            logger.debug("Message to plugin %s, %s", secret_key, kwargs["data"])

        engine.conn.register_event_handler(message_to_plugin)

        eloop = asyncio.get_event_loop()

        def stop_callback(success, message):
            if "aborting" in plugin_info:
                plugin_info["aborting"].set_result(success)
            message = str(message or "")
            logger.info(
                "Disconnecting from plugin (success: %s, message: %s)", success, message
            )
            coro = engine.conn.sio.emit(
                "message_from_plugin_" + secret_key,
                {
                    "type": "disconnected",
                    "details": {"success": success, "message": message},
                },
            )
            asyncio.run_coroutine_threadsafe(coro, eloop).result()

        def logging_callback(msg, type="info"):  # pylint: disable=redefined-builtin
            if msg == "":
                return
            coro = engine.conn.sio.emit(
                "message_from_plugin_" + secret_key,
                {"type": "logging", "details": {"value": msg, "type": type}},
            )
            asyncio.run_coroutine_threadsafe(coro, eloop).result()

        args = '{} -m {} --id="{}" --server={} --secret="{}"'.format(
            cmd, worker_module, pid, "http://127.0.0.1:" + engine.opt.port, secret_key
        )
        task_thread = threading.Thread(
            target=launch_plugin,
            args=[
                engine,
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
        task_thread.daemon = True
        task_thread.start()
        return {
            "success": True,
            "initialized": False,
            "secret": secret_key,
            "work_dir": os.path.abspath(work_dir),
        }

    except Exception:  # pylint: disable=broad-except
        traceback_error = traceback.format_exc()
        logger.error(traceback_error)
        return {"success": False, "reason": traceback_error}


@sio_on("register_client")
async def on_register_client(engine, sid, kwargs):
    """Register client."""
    logger = engine.logger
    conn_data = engine.store
    logger.info("Registering client: %s", kwargs)
    client_id = kwargs.get("id", str(uuid.uuid4()))
    workspace = kwargs.get("workspace", "default")
    session_id = kwargs.get("session_id", str(uuid.uuid4()))
    base_url = kwargs.get("base_url", engine.opt.base_url)
    if base_url.endswith("/"):
        base_url = base_url[:-1]

    token = kwargs.get("token")
    if token != engine.opt.token:
        logger.error("Wrong connection token (%s)", token)
        print("========>> Connection token: {} <<========".format(engine.opt.token))
        if engine.opt.engine_container_token is not None:
            await engine.conn.sio.emit(
                "message_to_container_" + engine.opt.engine_container_token,
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
        # except Exception as exc:
        #     logger.error("Failed to open the browser: %s", exc)
        conn_data.attempt_count += 1
        if conn_data.attempt_count >= MAX_ATTEMPTS:
            logger.info(
                "Client exited because max attemps exceeded: %s",
                conn_data.attempt_count,
            )
            sys.exit(100)
        return {"success": False, "message": "Connection token mismatch."}

    conn_data.attempt_count = 0
    if add_client_session(engine, session_id, client_id, sid, base_url, workspace):
        confirmation = True
        message = (
            "Another ImJoy session is connected to this Plugin Engine({}), "
            "allow a new session to connect?".format(base_url)
        )
    else:
        confirmation = False
        message = None

    engine_info = {"api_version": API_VERSION, "version": __version__}
    engine_info["platform"] = {
        "uname": ", ".join(platform.uname()),
        "machine": platform.machine(),
        "system": platform.system(),
        "processor": platform.processor(),
        "node": platform.node(),
    }

    try:
        gpus = GPUtil.getGPUs()
        engine_info["GPUs"] = [
            {
                "name": gpu.name,
                "id": gpu.id,
                "memory_total": gpu.memoryTotal,
                "memory_util": gpu.memoryUtil,
                "memoryUsed": gpu.memoryUsed,
                "driver": gpu.driver,
                "temperature": gpu.temperature,
                "load": gpu.load,
            }
            for gpu in gpus
        ]
    except Exception:  # pylint: disable=broad-except
        logger.error("Failed to get GPU information with GPUtil")

    return {
        "success": True,
        "confirmation": confirmation,
        "message": message,
        "engine_info": engine_info,
    }


@sio_on("kill_plugin")
async def on_kill_plugin(engine, sid, kwargs):
    """Kill plugin."""
    logger = engine.logger
    plugins = engine.store.plugins
    registered_sessions = engine.store.registered_sessions
    logger.info("Kill plugin: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered"}

    pid = kwargs["id"]
    if pid in plugins:
        if "killing" not in plugins[pid]:
            obj = {"force_kill": True, "pid": pid}
            plugins[pid]["killing"] = True

            def exited(_):
                obj["force_kill"] = False
                logger.info("Plugin %s exited normally", pid)
                # kill the plugin now
                kill_plugin(engine, pid)

            await engine.conn.sio.emit(
                "to_plugin_" + plugins[pid]["secret"],
                {"type": "disconnect"},
                callback=exited,
            )
            await force_kill_timeout(engine, engine.opt.force_quit_timeout, obj)
    return {"success": True}


@sio_on("kill_plugin_process")
async def on_kill_plugin_process(engine, sid, kwargs):
    """Kill plugin process."""
    logger = engine.logger
    plugins = engine.store.plugins
    registered_sessions = engine.store.registered_sessions
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered."}
    if "all" not in kwargs:
        return {
            "success": False,
            "error": 'You must provide the pid of the plugin process or "all=true".',
        }
    if kwargs["all"]:
        logger.info("Killing all the plugins")
        await kill_all_plugins(engine, sid)
        return {"success": True}
    try:
        kill_process(int(kwargs["pid"]), logger)
        return {"success": True}
    except Exception:  # pylint: disable=broad-except
        return {
            "success": False,
            "error": "Failed to kill plugin process: #" + str(kwargs["pid"]),
        }

    psutil = get_psutil()
    if not psutil:
        return
    current_process = psutil.Process()
    children = current_process.children(recursive=True)
    pids = []
    for proc in children:
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            pids.append(proc.pid)
    # remove plugin if the corresponding process does not exist any more
    for plugin in plugins.values():
        if plugin["process_id"] not in pids:
            plugin["process_id"] = None
            kill_plugin(engine, plugin["id"])


def resume_plugin_session(engine, pid, session_id, plugin_signature):
    """Resume plugin session."""
    logger = engine.logger
    plugins = engine.store.plugins
    plugin_sessions = engine.store.plugin_sessions
    plugin_signatures = engine.store.plugin_signatures
    if pid in plugins:
        if session_id in plugin_sessions:
            plugin_sessions[session_id].append(plugins[pid])
        else:
            plugin_sessions[session_id] = [plugins[pid]]

    if plugin_signature in plugin_signatures:
        plugin_info = plugin_signatures[plugin_signature]
        logger.info("Resuming plugin %s", pid)
        return plugin_info

    return None


def add_client_session(engine, session_id, client_id, sid, base_url, workspace):
    """Add client session."""
    logger = engine.logger
    clients = engine.store.clients
    registered_sessions = engine.store.registered_sessions
    if client_id in clients:
        clients[client_id].append(sid)
        client_connected = True
    else:
        clients[client_id] = [sid]
        client_connected = False
    logger.info("Adding client session %s", sid)
    registered_sessions[sid] = {
        "client": client_id,
        "session": session_id,
        "base_url": base_url,
        "workspace": workspace,
    }
    return client_connected


@sio_on("disconnect_client_session")
async def disconnect_client_session(engine, sid):
    """Disconnect client session."""
    logger = engine.logger
    clients = engine.store.clients
    plugin_sessions = engine.store.plugin_sessions
    registered_sessions = engine.store.registered_sessions
    if sid in registered_sessions:
        logger.info("Disconnecting client session %s", sid)
        obj = registered_sessions[sid]
        client_id, session_id = obj["client"], obj["session"]
        del registered_sessions[sid]
        if client_id in clients and sid in clients[client_id]:
            clients[client_id].remove(sid)
            if not clients[client_id]:
                del clients[client_id]
        if session_id in plugin_sessions:
            for plugin in plugin_sessions[session_id]:
                if "allow-detach" not in plugin["flags"]:
                    kill_plugin(engine, plugin["id"])
            del plugin_sessions[session_id]


def add_plugin(engine, plugin_info, sid=None):
    """Add plugin."""
    plugins = engine.store.plugins
    plugin_sessions = engine.store.plugin_sessions
    plugin_sids = engine.store.plugin_sids
    plugin_signatures = engine.store.plugin_signatures
    pid = plugin_info["id"]
    session_id = plugin_info["session_id"]
    plugin_signatures[plugin_info["signature"]] = plugin_info

    if pid not in plugins:
        if session_id in plugin_sessions:
            plugin_sessions[session_id].append(plugin_info)
        else:
            plugin_sessions[session_id] = [plugin_info]
    plugins[pid] = plugin_info

    if pid in plugins and sid is not None:
        plugin_sids[sid] = plugin_info
        plugin_info["sid"] = sid


@sio_on("disconnect_plugin")
async def disconnect_plugin(engine, sid):
    """Disconnect plugin."""
    logger = engine.logger
    plugins = engine.store.plugins
    plugin_sessions = engine.store.plugin_sessions
    plugin_sids = engine.store.plugin_sids
    plugin_signatures = engine.store.plugin_signatures
    if sid in plugin_sids:
        logger.info("Disconnecting plugin session %s", sid)
        pid = plugin_sids[sid]["id"]
        if pid in plugins:
            logger.info("Cleaning up plugin %s", pid)
            if plugins[pid]["signature"] in plugin_signatures:
                logger.info(
                    "Cleaning up plugin signature %s", plugins[pid]["signature"]
                )
                del plugin_signatures[plugins[pid]["signature"]]
            del plugins[pid]
        del plugin_sids[sid]
        for session_id in plugin_sessions.keys():
            exist = False
            for plugin in plugin_sessions[session_id]:
                if plugin["id"] == pid:
                    exist = plugin
            if exist:
                logger.info("Cleaning up plugin session %s", session_id)
                plugin_sessions[session_id].remove(exist)
                kill_plugin(engine, exist["id"])


def set_plugin_pid(engine, plugin_id, pid):
    """Set plugin pid."""
    plugins = engine.store.plugins
    plugins[plugin_id]["process_id"] = pid


def kill_plugin(engine, pid):
    """Kill plugin."""
    logger = engine.logger
    plugins = engine.store.plugins
    plugin_sids = engine.store.plugin_sids
    plugin_signatures = engine.store.plugin_signatures
    if pid in plugins:
        try:
            plugins[pid]["abort"].set()
            plugins[pid]["aborting"] = asyncio.get_event_loop().create_future()
            if plugins[pid]["process_id"] is not None:
                kill_process(plugins[pid]["process_id"], logger)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to kill plugin %s, error: %s", pid, exc)
        if "sid" in plugins[pid]:
            if plugins[pid]["sid"] in plugin_sids:
                del plugin_sids[plugins[pid]["sid"]]

        if plugins[pid]["signature"] in plugin_signatures:
            logger.info(
                "Cleaning up killed plugin signature %s", plugins[pid]["signature"]
            )
            del plugin_signatures[plugins[pid]["signature"]]
        logger.info("Cleaning up killed plugin %s", pid)
        del plugins[pid]


@sio_on("reset_engine_plugins")
async def reset_engine_plugins(engine, sid, _):
    """Handle plugins when reset engine is called."""
    await kill_all_plugins(engine, sid)


async def kill_all_plugins(engine, sid):
    """Kill all plugins."""
    logger = engine.logger
    plugin_sids = engine.store.plugin_sids
    # copy dict as it will change size when killing plugins
    for plugin_info in dict(plugin_sids).values():
        try:
            await on_kill_plugin(engine, sid, {"id": plugin_info["id"]})
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("%s", exc)


async def force_kill_timeout(engine, timeout, obj):
    """Force kill plugin after timeout."""
    logger = engine.logger
    pid = obj["pid"]
    for _ in range(int(timeout * 10)):
        if obj["force_kill"]:
            await asyncio.sleep(0.1)
        else:
            return

    logger.warning("Timeout, force quitting %s", pid)
    try:
        kill_plugin(engine, pid)
    except Exception as exc:  # pylint:disable=broad-except
        logger.error("Failed to kill plugin %s: %s", pid, exc)


def launch_plugin(
    engine,
    stop_callback,
    logging_callback,
    plugin_id,
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
    logger = engine.logger
    opt = engine.opt
    if abort.is_set():
        logger.info("Plugin aborting")
        logging_callback("Plugin aborting")
        return False
    venv_name = None
    progress = 0
    try:
        repos = parse_repos(requirements, work_dir)
        progress = 5
        logging_callback(progress, type="progress")
        for repo in repos:
            try:
                logger.info("Cloning repo %s to %s", repo["url"], repo["repo_dir"])
                logging_callback(f"Cloning repo {repo['url']} to {repo['repo_dir']}")
                if os.path.exists(repo["repo_dir"]):
                    assert os.path.isdir(repo["repo_dir"])
                    cmd = "git pull --all"
                    run_cmd(
                        engine,
                        cmd.split(" "),
                        cwd=repo["repo_dir"],
                        plugin_id=plugin_id,
                    )
                else:
                    cmd = (
                        "git clone --progress --depth=1 "
                        + repo["url"]
                        + " "
                        + repo["repo_dir"]
                    )
                    run_cmd(engine, cmd.split(" "), cwd=work_dir, plugin_id=plugin_id)
                progress += int(20 / len(repos))
                logging_callback(progress, type="progress")
            except Exception as exc:  # pylint: disable=broad-except
                logging_callback(f"Failed to obtain the git repo: {exc}", type="error")

        default_virtual_env = "{}-{}".format(pname, tag) if tag != "" else pname
        default_virtual_env = default_virtual_env.replace(" ", "_")
        venv_name, envs, is_py2 = parse_env(engine, env, work_dir, default_virtual_env)
        environment_variables = {}

        if engine.opt.dev:
            default_requirements = ["imjoy[worker]"]
        else:
            default_requirements = ["imjoy[worker]==" + __version__]
        default_reqs_cmds = parse_requirements(
            default_requirements, conda=opt.conda_available
        )
        reqs_cmds = parse_requirements(requirements, opt.conda_available)
        reqs_cmds += default_reqs_cmds

        cmd_history = engine.store.cmd_history

        def process_start(pid=None, cmd=None):
            """Run before process starts."""
            if pid is not None:
                set_plugin_pid(engine, plugin_id, pid)
            if cmd is not None:
                logger.info("Running command %s", cmd)

        def process_finish(pid=None, cmd=None):
            """Notify when an install process command has finished."""
            logger.debug("Finished running (pid=%s): %s", pid, cmd)
            nonlocal progress
            progress += int(70 / (len(envs) + len(reqs_cmds)))
            logging_callback(progress, type="progress")

        for _env in envs:
            if isinstance(_env, str):
                if _env not in cmd_history:
                    logger.info("Running env command: %s", _env)
                    logging_callback(f"Running env command: {_env}")
                    code, errors = run_process(
                        _env.split(),
                        process_start=process_start,
                        process_finish=process_finish,
                        env=plugin_env,
                        cwd=work_dir,
                    )

                    if code == 0:
                        cmd_history.append(_env)
                        logging_callback("Successful execution of env command")

                    if errors is not None:
                        logging_callback(str(errors, "utf-8"), type="error")

                else:
                    logger.debug("Skip env command: %s", _env)
                    logging_callback(f"Skip env command: {_env}")

            elif isinstance(_env, dict):
                assert "type" in _env
                if _env["type"] == "gputil":
                    # Set CUDA_DEVICE_ORDER
                    # so the IDs assigned by CUDA match those from nvidia-smi
                    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
                    device_ids = GPUtil.getAvailable(**_env["options"])
                    if not device_ids:
                        raise Exception("No GPU is available to run this plugin.")
                    environment_variables["CUDA_VISIBLE_DEVICES"] = ",".join(
                        [str(device_id) for device_id in device_ids]
                    )
                    logging_callback(f"GPU id assigned: {device_ids}")
                elif _env["type"] == "variable":
                    environment_variables.update(_env["options"])
            else:
                logger.debug("Skip unsupported env: %s", _env)

            if abort.is_set():
                logger.info("Plugin aborting")
                return False

        if opt.freeze:
            logger.warning(
                "pip command is blocked due to `--freeze` mode: %s", reqs_cmds
            )
            reqs_cmds = []

        elif opt.conda_available and venv_name is not None:
            reqs_cmds = apply_conda_activate(reqs_cmds, opt.conda_activate, venv_name)

        install_reqs(
            engine,
            plugin_env,
            work_dir,
            reqs_cmds,
            process_start,
            process_finish,
            logging_callback,
        )

    except Exception:  # pylint: disable=broad-except
        error_traceback = traceback.format_exc()
        logger.error(
            "Failed to setup plugin virtual environment or its requirements: %s",
            error_traceback,
        )
        abort.set()
        stop_callback(False, f"Plugin process failed to start: {error_traceback}")
        return False

    if abort.is_set():
        logger.info("Plugin aborting")
        stop_callback(False, "Plugin process failed to start")
        return False
    # env = os.environ.copy()
    if opt.conda_available and venv_name is not None:
        [args] = apply_conda_activate([args], opt.conda_activate, venv_name)
    if isinstance(args, str):
        args = args.split()
    if not args:
        args = []
    # Convert them all to strings
    args = [str(x) for x in args if str(x) != ""]
    logger.info("Plugin %s task started", name)

    args = " ".join(args)
    logger.info("Task subprocess args: %s", args)

    # set system/version dependent "start_new_session" analogs
    # https://docs.python.org/2/library/subprocess.html#converting-argument-sequence
    kwargs = {}
    if sys.platform != "win32":
        kwargs.update(preexec_fn=os.setsid)
    progress = 100
    logging_callback(progress, type="progress")
    try:
        _env = plugin_env.copy()
        _env.update(environment_variables)
        logger.debug("Running process with env: %s", _env)
        process = subprocess.Popen(
            args,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            env=_env,
            cwd=work_dir,
            **kwargs,
        )
        logging_callback(f"Running subprocess (pid={process.pid}) with {args}")
        set_plugin_pid(engine, plugin_id, process.pid)
        # Poll process for new output until finished
        stdfn = sys.stdout.fileno()

        progress = 0
        logging_callback(progress, type="progress")

        while True:
            out = process.stdout.read(1)
            if out == "" and process.poll() is not None:
                break
            os.write(stdfn, out)
            sys.stdout.flush()
            if abort.is_set() or process.poll() is not None:
                break
            time.sleep(0)

        logger.info("Plugin aborting")
        kill_process(process.pid, logger)

        outputs, errors = process.communicate()
        if outputs is not None:
            outputs = str(outputs, "utf-8")
        if errors is not None:
            errors = str(errors, "utf-8")
        exit_code = process.returncode
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(traceback.format_exc())
        outputs, errors = "", str(exc)
        exit_code = 100
    if exit_code == 0:
        logging_callback(f"Plugin process exited with code {exit_code}")
        stop_callback(True, outputs)
        return True

    logging_callback(f"Plugin process exited with code {exit_code}", type="error")
    logger.error(
        "Error occured during terminating a process.\n" "Command: %s\nExit code: %s",
        args,
        exit_code,
    )
    errors = errors or ""
    stop_callback(False, f"{errors}\nPlugin process exited with code {exit_code}")
    return False


def run_cmd(
    engine,
    cmd,
    shell=False,
    cwd=None,
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
        set_plugin_pid(engine, plugin_id, proc.pid)

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
        raise Exception(f"Command failed with code {code}: {cmd}")
    return output
