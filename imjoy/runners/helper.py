import shlex
import shutil
import subprocess
from pathlib import Path

import yaml


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
    errors = None

    for cmd in reqs_cmds:
        if cmd in cmd_history:
            logger.debug("skip command: %s", cmd)
            continue
        commands.append(cmd)

    def fail_install():
        """Notify of failed installation."""
        logging_callback(
            f"Failed to install dependencies with exit code {code} and error: {errors}",
            type="error",
        )
        raise Exception(
            f"Failed to install dependencies with exit code {code} and error: {errors}"
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

    if not engine.opt.conda_available:
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
        if opt.freeze or not opt.conda_available:
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
