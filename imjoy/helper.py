"""Provide helper functions that are aware of the ImJoy engine."""
import copy
import logging
import os
import shlex
import shutil
import subprocess
from importlib import import_module
from pathlib import Path

import yaml


class dotdict(dict):  # pylint: disable=invalid-name
    """Access dictionary attributes with dot.notation."""

    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __deepcopy__(self, memo=None):
        """Make a deep copy."""
        return dotdict(copy.deepcopy(dict(self), memo=memo))


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


def kill_process(logger, pid):
    """Kill process."""
    psutil = get_psutil()
    if psutil is None:
        return
    logger.info("Killing plugin process (pid=%s)", pid)
    try:
        current_process = psutil.Process(pid)
        for proc in current_process.children(recursive=True):
            try:
                if proc.is_running():
                    proc.kill()
            except psutil.NoSuchProcess:
                logger.info("Subprocess %s has already been killed", pid)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Failed to kill a subprocess (pid=%s). Error: %s", pid, exc
                )
        current_process.kill()
        logger.info("Plugin process %s was killed.", pid)
    except psutil.NoSuchProcess:
        logger.info("Process %s has already been killed", pid)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to kill a process (pid=%s), "
            "you may want to kill it manually. Error: %s",
            pid,
            exc,
        )


def parse_requirements(reqs, conda=False):
    """Parse requirements.

    Return a list of commands to install the requirements.
    """
    commands = []
    if not isinstance(reqs, list):
        reqs = [reqs]
    reqs = [str(req) for req in reqs]

    for req in reqs:
        if ":" in req:
            req_parts = req.split(":")
            typ, libs = req_parts[0], ":".join(req_parts[1:])
            typ, libs = typ.strip(), libs.strip()
            libs = [l.strip() for l in libs.split(" ") if l.strip()]
            if typ == "conda" and libs and conda:
                commands.append("conda install -y " + " ".join(libs))
            elif typ == "pip" and libs:
                commands.append("pip install " + " ".join(libs))
            elif typ == "repo" and libs:
                pass
            elif typ == "cmd" and libs:
                commands.append(" ".join(libs))
            elif "+" in typ or "http" in typ:
                commands.append(f"pip install {req}")
            else:
                raise Exception(f"Unsupported requirement type: {typ}")
        else:
            commands.append(f"pip install {req}")

    return commands


def apply_conda_activate(reqs_cmds, conda_activate, venv_name):
    """Apply the conda activate command to conda install commands."""
    return [conda_activate.format(f"{venv_name} && {cmd}") for cmd in reqs_cmds]


def install_reqs(
    engine, env, work_dir, reqs_cmds, process_start, process_finish, logging_callback
):
    """Install requirements including fallback handling."""
    logger = engine.logger
    cmd_history = engine.store.cmd_history
    commands = []
    code = 0
    error = None

    for cmd in reqs_cmds:
        if cmd in cmd_history:
            logger.debug("skip command: %s", cmd)
            continue
        commands.append(cmd)

    def fail_install():
        """Notify of failed installation."""
        logging_callback(
            f"Failed to install dependencies with exit code {code} and error: {error}",
            type="error",
        )
        raise Exception(
            f"Failed to install dependencies with exit code {code} and error: {error}"
        )

    def _process_start(pid=None, cmd=None):
        """Run after starting the process."""
        logging_callback(f"Running requirements subprocess(pid={pid}): {cmd}")
        process_start(pid=pid)

    logger.info("Running requirements commands: %s", commands)
    code, errors = run_commands(env, work_dir, commands, _process_start, process_finish)

    if code == 0:
        cmd_history.extend(commands)
        logging_callback("Requirements command executed successfully.")
        return
    logging_callback(f"Failed to run requirements command: {commands}", type="error")
    if errors is not None:
        logging_callback(str(errors, "utf-8"), type="error")

    if not engine.opt.CONDA_AVAILABLE:
        fail_install()

    git_cmd = ""
    if shutil.which("git") is None:
        git_cmd += " git"
    if shutil.which("pip") is None:
        git_cmd += " pip"
    if git_cmd == "":
        fail_install()

    logger.info("pip command failed, trying to install git and pip")
    # try to install git and pip
    git_cmd = f"conda install -y{git_cmd}"
    code, _ = run_process(
        git_cmd.split(),
        process_start=_process_start,
        stderr=None,
        env=env,
        cwd=work_dir,
    )
    if code != 0:
        fail_install()

    logger.info("Running requirements commands: %s", commands)
    code, errors = run_commands(env, work_dir, commands, _process_start, process_finish)

    if code != 0:
        fail_install()


def run_commands(env, work_dir, commands, process_start, process_finish):
    """Run commands in separate processes."""
    code = 0
    errors = None

    for cmd in commands:
        print("Running command:", cmd)
        code, errors = run_process(
            cmd,
            process_start=process_start,
            process_finish=process_finish,
            shell=True,
            env=env,
            cwd=work_dir,
        )
        if code:
            return code, errors

    return code, errors


def run_process(cmd, process_start=None, process_finish=None, **kwargs):
    """Run subprocess command."""
    shell = kwargs.pop("shell", False)
    stderr = kwargs.pop("stderr", subprocess.PIPE)
    process = subprocess.Popen(cmd, shell=shell, stderr=stderr, **kwargs)
    if process_start is not None:
        process_start(pid=process.pid, cmd=cmd)
    return_code = process.wait()
    if stderr is not None:
        _, errors = process.communicate()
    else:
        errors = None
    if process_finish is not None:
        process_finish(pid=process.pid, cmd=cmd)

    return return_code, errors


def parse_env(engine, envs, work_dir, default_env_name):
    """Parse environment."""
    venv_name = None
    is_py2 = False
    logger = engine.logger
    opt = engine.opt

    if isinstance(envs, str):
        envs = envs.strip()

    if not envs:
        if opt.freeze or not opt.CONDA_AVAILABLE:
            logger.warning(
                "env command is blocked because conda is not available "
                "or in `--freeze` mode: %s",
                envs,
            )
        return venv_name, [], is_py2

    if not isinstance(envs, list):
        envs = [envs]
    for i, env in enumerate(envs):
        if "conda create" in env:
            if "python=2" in env:
                is_py2 = True
            parms = shlex.split(env)
            if "-n" in parms:
                venv_name = parms[parms.index("-n") + 1]
            elif "--name" in parms:
                venv_name = parms[parms.index("--name") + 1]
            else:
                venv_name = default_env_name
                envs[i] = env.replace("conda create", "conda create -n " + venv_name)

            if "-y" not in parms:
                envs[i] = env.replace("conda create", "conda create -y")

        if "conda env create" in env:
            parms = shlex.split(env)
            if "-f" in parms:
                try:
                    env_file = Path(work_dir) / parms[parms.index("-f") + 1]
                    with open(env_file, "r") as stream:
                        env_config = yaml.load(stream)
                        assert "name" in env_config
                        venv_name = env_config["name"]
                except Exception as exc:
                    raise Exception(
                        f"Failed to read env name from the specified env file: {exc}"
                    )

            else:
                raise Exception(
                    "You should provide an environment file via `conda env create -f`"
                )

    if not venv_name or not venv_name.strip():
        venv_name = None

    return venv_name, envs, is_py2


def scandir(path, type_=None, recursive=False):
    """Scan a directory for a type of files return a list of files found."""
    file_list = []
    for fil in os.scandir(path):
        if fil.name.startswith("."):
            continue
        if type_ is None or type_ == "file":
            if os.path.isdir(fil.path):
                if recursive:
                    file_list.append(
                        {
                            "name": fil.name,
                            "type": "dir",
                            "children": scandir(fil.path, type_, recursive),
                        }
                    )
                else:
                    file_list.append({"name": fil.name, "type": "dir"})
            else:
                file_list.append({"name": fil.name, "type": "file"})
        elif type_ == "directory":
            if os.path.isdir(fil.path):
                file_list.append({"name": fil.name})
    return file_list


def setup_logging(opt, logger):
    """Set up logging."""
    if opt.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
