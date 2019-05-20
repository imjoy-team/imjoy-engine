"""Provide helper functions that are aware of the ImJoy engine."""
import copy
import logging
import os
import shlex
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
