"""Provide a plugin manager."""
import asyncio
import datetime
import os
import subprocess
import sys
import time
import traceback

import GPUtil
from imjoy.const import (
    DEFAULT_REQUIREMENTS_PY2,
    DEFAULT_REQUIREMENTS_PY3,
    NAME_SPACE,
    REQ_PSUTIL,
    REQ_PSUTIL_CONDA,
)
from imjoy.helper import (
    apply_conda_activate,
    install_reqs,
    kill_process,
    parse_env,
    parse_requirements,
    run_commands,
    run_process,
)
from imjoy.util import console_to_str, parse_repos


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


def disconnect_client_session(engine, sid):
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


def disconnect_plugin(engine, sid):
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
                kill_process(logger, plugins[pid]["process_id"])
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


async def kill_all_plugins(engine, ssid):
    """Kill all plugins."""
    logger = engine.logger
    on_kill_plugin = engine.conn.sio.handlers[NAME_SPACE]["kill_plugin"]
    plugin_sids = engine.store.plugin_sids
    tasks = []
    for sid in list(plugin_sids.keys()):
        try:
            await on_kill_plugin(ssid, {"id": plugin_sids[sid]["id"]})
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("%s", exc)

    return asyncio.gather(*tasks)


async def force_kill_timeout(engine, timeout, obj):
    """Force kill plugin after timeout."""
    logger = engine.logger
    pid = obj["pid"]
    for _ in range(int(timeout * 10)):
        if obj["force_kill"]:
            await asyncio.sleep(0.1)
        else:
            return
    try:
        logger.warning("Timeout, force quitting %s", pid)
        kill_plugin(engine, pid)
    finally:
        return  # TODO: What is the idea behind the return inside finally?


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
        default_requirements = (
            DEFAULT_REQUIREMENTS_PY2 if is_py2 else DEFAULT_REQUIREMENTS_PY3
        )
        default_reqs_cmds = parse_requirements(
            default_requirements, conda=opt.CONDA_AVAILABLE
        )
        reqs_cmds = parse_requirements(requirements, opt.CONDA_AVAILABLE)
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
            progress += int(70 / (len(envs) + len(reqs_cmds) + len(REQ_PSUTIL)))
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

        elif opt.CONDA_AVAILABLE and venv_name is not None:
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

        if not opt.freeze:
            psutil_cmds = parse_requirements(REQ_PSUTIL)
            logger.info("Running requirements commands: %s", psutil_cmds)
            code, _ = run_commands(
                plugin_env, work_dir, psutil_cmds, process_start, process_finish
            )
        if not opt.freeze and code and opt.CONDA_AVAILABLE and venv_name is not None:
            logger.info("Failed installing psutil with pip, trying conda")
            psutil_cmds = parse_requirements(
                REQ_PSUTIL_CONDA, conda=opt.CONDA_AVAILABLE
            )
            psutil_cmds = apply_conda_activate(
                psutil_cmds, opt.conda_activate, venv_name
            )
            logger.info("Running requirements commands: %s", psutil_cmds)
            code, _ = run_commands(
                plugin_env, work_dir, psutil_cmds, process_start, process_finish
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
    if opt.CONDA_AVAILABLE and venv_name is not None:
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
        kill_process(logger, process.pid)

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
