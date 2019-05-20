"""Provide a plugin manager."""
import asyncio
import datetime
import os
import shutil
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
from imjoy.helper import killProcess, parseRequirements, parseEnv
from imjoy.util import console_to_str, parseRepos


def resumePluginSession(eng, pid, session_id, plugin_signature):
    """Resume plugin session."""
    logger = eng.logger
    plugins = eng.store.plugins
    plugin_sessions = eng.store.plugin_sessions
    plugin_signatures = eng.store.plugin_signatures
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


def addClientSession(eng, session_id, client_id, sid, base_url, workspace):
    """Add client session."""
    logger = eng.logger
    clients = eng.store.clients
    registered_sessions = eng.store.registered_sessions
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


def disconnectClientSession(eng, sid):
    """Disconnect client session."""
    logger = eng.logger
    clients = eng.store.clients
    plugin_sessions = eng.store.plugin_sessions
    registered_sessions = eng.store.registered_sessions
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
                    killPlugin(eng, plugin["id"])
            del plugin_sessions[session_id]


def addPlugin(eng, plugin_info, sid=None):
    """Add plugin."""
    plugins = eng.store.plugins
    plugin_sessions = eng.store.plugin_sessions
    plugin_sids = eng.store.plugin_sids
    plugin_signatures = eng.store.plugin_signatures
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


def disconnectPlugin(eng, sid):
    """Disconnect plugin."""
    logger = eng.logger
    plugins = eng.store.plugins
    plugin_sessions = eng.store.plugin_sessions
    plugin_sids = eng.store.plugin_sids
    plugin_signatures = eng.store.plugin_signatures
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
                killPlugin(eng, exist["id"])


def setPluginPID(eng, plugin_id, pid):
    """Set plugin pid."""
    plugins = eng.store.plugins
    plugins[plugin_id]["process_id"] = pid


def killPlugin(eng, pid):
    """Kill plugin."""
    logger = eng.logger
    plugins = eng.store.plugins
    plugin_sids = eng.store.plugin_sids
    plugin_signatures = eng.store.plugin_signatures
    if pid in plugins:
        try:
            plugins[pid]["abort"].set()
            plugins[pid]["aborting"] = asyncio.get_event_loop().create_future()
            if plugins[pid]["process_id"] is not None:
                killProcess(logger, plugins[pid]["process_id"])
                print('INFO: "{}" was killed.'.format(pid))
        except Exception as exc:  # pylint: disable=broad-except
            print('WARNING: failed to kill plugin "{}".'.format(pid))
            logger.error(str(exc))
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


async def killAllPlugins(eng, ssid):
    """Kill all plugins."""
    logger = eng.logger
    on_kill_plugin = eng.conn.sio.handlers[NAME_SPACE]["kill_plugin"]
    plugin_sids = eng.store.plugin_sids
    tasks = []
    for sid in list(plugin_sids.keys()):
        try:
            await on_kill_plugin(ssid, {"id": plugin_sids[sid]["id"]})
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(str(exc))

    return asyncio.gather(*tasks)


async def force_kill_timeout(eng, t, obj):
    """Force kill plugin after timeout."""
    logger = eng.logger
    pid = obj["pid"]
    for _ in range(int(t * 10)):
        if obj["force_kill"]:
            await asyncio.sleep(0.1)
        else:
            return
    try:
        logger.warning("Timeout, force quitting %s", pid)
        killPlugin(eng, pid)
    finally:
        return


def launch_plugin(
    eng,
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
    logger = eng.logger
    opt = eng.opt
    plugins = eng.store.plugins
    if abort.is_set():
        logger.info("plugin aborting...")
        logging_callback("plugin aborting...")
        return False
    virtual_env_name = None
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
                    runCmd(eng, cmd.split(" "), cwd=r["repo_dir"], plugin_id=pid)
                else:
                    cmd = (
                        "git clone --progress --depth=1 "
                        + r["url"]
                        + " "
                        + r["repo_dir"]
                    )
                    runCmd(eng, cmd.split(" "), cwd=work_dir, plugin_id=pid)
                logging_callback(k * 5, type="progress")
            except Exception as ex:  # pylint: disable=broad-except
                logging_callback(
                    "Failed to obtain the git repo: " + str(ex), type="error"
                )

        default_virtual_env = "{}-{}".format(pname, tag) if tag != "" else pname
        default_virtual_env = default_virtual_env.replace(" ", "_")
        virtual_env_name, envs, is_py2 = parseEnv(
            eng, env, work_dir, default_virtual_env
        )
        environment_variables = {}
        default_requirements = (
            DEFAULT_REQUIREMENTS_PY2 if is_py2 else DEFAULT_REQUIREMENTS_PY3
        )
        default_requirements_cmd = parseRequirements(
            default_requirements, conda=opt.CONDA_AVAILABLE
        )
        requirements_cmd = parseRequirements(
            requirements, default_requirements_cmd, opt.CONDA_AVAILABLE
        )

        cmd_history = eng.store.cmd_history

        if envs is not None and len(envs) > 0:
            for env in envs:
                if type(env) is str:
                    print("Running env command: " + env)
                    logger.info("running env command: %s", env)
                    if env not in cmd_history:
                        logging_callback("running env command: {}".format(env))
                        code, errors = run_process(
                            eng, pid, env.split(), env=plugin_env, cwd=work_dir
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

                elif type(env) is dict:
                    assert "type" in env
                    if env["type"] == "gputil":
                        # Set CUDA_DEVICE_ORDER so the IDs assigned by CUDA match those from nvidia-smi
                        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
                        deviceIDs = GPUtil.getAvailable(**env["options"])
                        if len(deviceIDs) <= 0:
                            raise Exception("No GPU is available to run this plugin.")
                        environment_variables["CUDA_VISIBLE_DEVICES"] = ",".join(
                            [str(deviceID) for deviceID in deviceIDs]
                        )
                        logging_callback("GPU id assigned: " + str(deviceIDs))
                    elif env["type"] == "variable":
                        environment_variables.update(env["options"])
                else:
                    logger.debug("skip unsupported env: %s", env)

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

        if not opt.freeze and opt.CONDA_AVAILABLE and virtual_env_name is not None:
            requirements_cmd = opt.conda_activate.format(
                virtual_env_name + " && " + requirements_cmd
            )

        logger.info("Running requirements command: %s", requirements_cmd)
        print("Running requirements command: ", requirements_cmd)
        if requirements_cmd is not None and requirements_cmd not in cmd_history:
            code, errors = run_process(
                eng, pid, requirements_cmd, shell=True, env=plugin_env, cwd=work_dir
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
                        eng,
                        pid,
                        git_cmd.split(),
                        stderr=None,
                        env=plugin_env,
                        cwd=work_dir,
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
                            eng,
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
                eng,
                pid,
                psutil_cmd,
                shell=True,
                stderr=None,
                env=plugin_env,
                cwd=work_dir,
            )
        if (
            not opt.freeze
            and code
            and opt.CONDA_AVAILABLE
            and virtual_env_name is not None
        ):
            psutil_cmd = parseRequirements(REQ_PSUTIL_CONDA, conda=opt.CONDA_AVAILABLE)
            psutil_cmd = opt.conda_activate.format(
                "{} && {}".format(virtual_env_name, psutil_cmd)
            )
            code, _ = run_process(
                eng,
                pid,
                psutil_cmd,
                shell=True,
                stderr=None,
                env=plugin_env,
                cwd=work_dir,
            )

    except Exception:  # pylint: disable=broad-except
        error_traceback = traceback.format_exc()
        print(error_traceback)
        logger.error(
            "Failed to setup plugin virtual environment or its requirements: %s",
            error_traceback,
        )
        abort.set()
        stop_callback(False, "Plugin process failed to start: " + error_traceback)
        return False

    if abort.is_set():
        logger.info("Plugin aborting...")
        stop_callback(False, "Plugin process failed to start")
        return False
    # env = os.environ.copy()
    if opt.CONDA_AVAILABLE and virtual_env_name is not None:
        args = opt.conda_activate.format(virtual_env_name + " && " + args)
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
        _env = plugin_env.copy()
        _env.update(environment_variables)
        logger.debug("running process with env: %s", _env)
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
        logging_callback("running subprocess(pid={}) with {}".format(process.pid, args))
        setPluginPID(eng, pid, process.pid)
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
        killProcess(logger, process.pid)

        outputs, errors = process.communicate()
        if outputs is not None:
            outputs = str(outputs, "utf-8")
        if errors is not None:
            errors = str(errors, "utf-8")
        exitCode = process.returncode
    except Exception as exc:  # pylint: disable=broad-except
        print(traceback.format_exc())
        outputs, errors = "", str(exc)
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


def run_process(eng, plugin_id, cmd, **kwargs):
    """Run subprocess command."""
    shell = kwargs.pop("shell", False)
    stderr = kwargs.pop("stderr", subprocess.PIPE)
    process_ = subprocess.Popen(cmd, shell=shell, stderr=stderr, **kwargs)
    setPluginPID(eng, plugin_id, process_.pid)
    return_code = process_.wait()
    if stderr is not None:
        _, errors = process_.communicate()
    else:
        errors = None

    return return_code, errors


def runCmd(
    eng,
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
        setPluginPID(eng, plugin_id, proc.pid)

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
