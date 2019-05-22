"""Provide helper functions that are aware of the ImJoy engine."""
import copy
import logging
import os
import shlex
import shutil
import subprocess
from importlib import import_module

import yaml


class dotdict(dict):
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


def killProcess(logger, pid):
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
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "WARNING: failed to kill a subprocess (PID={}). Error: {}".format(
                        pid, str(exc)
                    )
                )
        cp.kill()
        logger.info("plugin process %s was killed.", pid)
    except psutil.NoSuchProcess:
        logger.info("process %s has already been killed", pid)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "WARNING: failed to kill a process (PID={}), "
            "you may want to kill it manually. Error: {}".format(pid, str(exc))
        )


def parseRequirements(requirements, default_command=None, conda=False):
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
                if tp == "conda" and len(libs) > 0 and conda:
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


def install_reqs_fallback(
    eng, env, work_dir, reqs_cmd, process_start, process_finish, logging_callback
):
    """Install requirements including fallback handling."""
    logger = eng.logger
    cmd_history = eng.store.cmd_history
    if reqs_cmd is None or reqs_cmd in cmd_history:
        logger.debug("skip command: %s", reqs_cmd)
        return

    code = 0
    error = None

    def fail_install():
        """Notify of failed installation."""
        logging_callback(
            f"Failed to install dependencies with exit code {code} and error: {error}",
            type="error",
        )
        raise Exception(
            f"Failed to install dependencies with exit code {code} and error: {error}"
        )

    def _process_start(process_pid):
        """Run after starting the process."""
        logging_callback(
            f"Running requirements subprocess(pid={process_pid}): {reqs_cmd}"
        )
        process_start(process_pid)

    logger.info("Running requirements command: %s", reqs_cmd)
    code, errors = install_reqs(env, work_dir, reqs_cmd, _process_start, process_finish)

    if code == 0:
        cmd_history.append(reqs_cmd)
        logging_callback("Requirements command executed successfully.")
        logging_callback(70, type="progress")
        return
    logging_callback(f"Failed to run requirements command: {reqs_cmd}", type="error")
    if errors is not None:
        logging_callback(str(errors, "utf-8"), type="error")

    if not eng.opt.CONDA_AVAILABLE:
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
        git_cmd.split(), callback=_process_start, stderr=None, env=env, cwd=work_dir
    )
    if code != 0:
        fail_install()

    logger.info("Running requirements command: %s", reqs_cmd)
    code, errors = install_reqs(env, work_dir, reqs_cmd, _process_start, process_finish)

    if code != 0:
        fail_install()


def install_reqs(env, work_dir, reqs_cmd, process_start, process_finish):
    """Install requirements."""
    code = 0
    errors = None
    commands = reqs_cmd.split(" && ")

    for cmd in commands:
        print("Running command:", cmd)
        code, errors = run_process(
            cmd, callback=process_start, shell=True, env=env, cwd=work_dir
        )
        if code:
            return code, errors
        process_finish(cmd)

    return code, errors


def run_process(cmd, callback=None, **kwargs):
    """Run subprocess command."""
    shell = kwargs.pop("shell", False)
    stderr = kwargs.pop("stderr", subprocess.PIPE)
    process_ = subprocess.Popen(cmd, shell=shell, stderr=stderr, **kwargs)
    if callback is not None:
        callback(process_.pid)
    return_code = process_.wait()
    if stderr is not None:
        _, errors = process_.communicate()
    else:
        errors = None

    return return_code, errors


def parseEnv(eng, env, work_dir, default_env_name):
    """Parse environment."""
    virtual_env_name = ""
    is_py2 = False
    envs = None
    logger = eng.logger
    opt = eng.opt

    if type(env) is str:
        env = None if env.strip() == "" else env

    if env is not None:
        if not opt.freeze and opt.CONDA_AVAILABLE:
            if type(env) is str:
                envs = [env]
            else:
                envs = env
            for i, _env in enumerate(envs):
                if type(_env) is str:
                    if "conda create" in _env:
                        if "python=2" in _env:
                            is_py2 = True
                        parms = shlex.split(_env)
                        if "-n" in parms:
                            virtual_env_name = parms[parms.index("-n") + 1]
                        elif "--name" in parms:
                            virtual_env_name = parms[parms.index("--name") + 1]
                        else:
                            virtual_env_name = default_env_name
                            envs[i] = _env.replace(
                                "conda create", "conda create -n " + virtual_env_name
                            )

                        if "-y" not in parms:
                            envs[i] = _env.replace("conda create", "conda create -y")

                    if "conda env create" in _env:
                        parms = shlex.split(_env)
                        if "-f" in parms:
                            try:
                                env_file = os.path.join(
                                    work_dir, parms[parms.index("-f") + 1]
                                )
                                with open(env_file, "r") as stream:
                                    env_config = yaml.load(stream)
                                    assert "name" in env_config
                                    virtual_env_name = env_config["name"]
                            except Exception as exc:
                                raise Exception(
                                    "Failed to read the env name "
                                    "from the specified env file: " + str(exc)
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

    if virtual_env_name.strip() == "":
        virtual_env_name = None

    return virtual_env_name, envs, is_py2


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
        logger.setLevel(logging.ERROR)
