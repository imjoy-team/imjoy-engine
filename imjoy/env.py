"""Provide setup function to prepare the engine."""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

from imjoy.utils import kill_process


def prepare_env(opt, logger):
    """Prepare environment."""
    opt.conda_available = False
    # add executable path to PATH
    os.environ["PATH"] = (
        os.path.split(sys.executable)[0] + os.pathsep + os.environ.get("PATH", "")
    )

    try:
        process = subprocess.Popen(
            ["conda", "info", "--json", "-s"], stdout=subprocess.PIPE
        )
        cout, _ = process.communicate()
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
        opt.conda_available = True
    except OSError:
        conda_prefix = None
        if sys.version_info < (3, 0):
            sys.exit(
                "Sorry, ImJoy plugin engine can only run within a conda environment "
                "or at least in Python 3."
            )
        logger.warning(
            "You are running ImJoy without conda, "
            "you may have problems with some plugins"
        )

    if opt.conda_available:
        if sys.platform == "linux" or sys.platform == "linux2":
            # linux
            opt.conda_activate = (
                "/bin/bash -c 'source " + conda_prefix + "/bin/activate {}'"
            )
        elif sys.platform == "darwin":
            # OS X
            opt.conda_activate = "source activate {}"
        elif sys.platform == "win32":
            # Windows...
            opt.conda_activate = "activate {}"
        else:
            opt.conda_activate = "conda activate {}"
    else:
        opt.conda_activate = "{}"

    return opt


def bootstrap(opt, logger):
    """Bootstrap the engine."""
    if not opt.conda_available and not opt.freeze:
        logger.warning(
            "Command `pip install` may not work, "
            "in that case you may want to add `--freeze`"
        )

    if opt.freeze:
        logger.warning(
            "You are running the plugin engine with `--freeze`, "
            "this means you need to handle all the plugin requirements yourself"
        )

    opt.workspace_dir = os.path.expanduser(opt.workspace)
    if not os.path.exists(opt.workspace_dir):
        os.makedirs(opt.workspace_dir)

    # read token from file if exists
    try:
        if opt.token is None or opt.token == "":
            with open(os.path.join(opt.workspace_dir, ".token"), "r") as fil:
                opt.token = fil.read()
    except Exception:  # pylint: disable=broad-except
        logger.debug("Failed to read token from file")

    try:
        if opt.token is None or opt.token == "":
            opt.token = str(uuid.uuid4())
            with open(os.path.join(opt.workspace_dir, ".token"), "w") as fil:
                fil.write(opt.token)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to save .token file: %s", str(exc))

    # try to kill last process
    pid_file = os.path.join(opt.workspace_dir, ".pid")
    try:
        if os.path.exists(pid_file):
            with open(pid_file, "r") as fil:
                pid = int(fil.read())
                logger.info("Trying to kill last process (pid=%s)", pid)
                kill_process(pid, logger)
                # wait for a while to release the port
                time.sleep(3)

    except Exception:  # pylint: disable=broad-except
        logger.debug("Failed to kill last process")
    try:
        engine_pid = str(os.getpid())
        with open(pid_file, "w") as fil:
            fil.write(engine_pid)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to save .pid file: %s", str(exc))

    opt.web_app_dir = os.path.join(opt.workspace_dir, "__ImJoy__")
    if opt.serve:
        if shutil.which("git") is None:
            logger.info("Installing git")
            ret = subprocess.Popen(
                "conda install -y git && git clone -b gh-pages --depth 1 "
                "https://github.com/oeway/ImJoy".split(),
                shell=False,
            ).wait()
            if ret != 0:
                logger.error(
                    "Failed to install git, "
                    "please check whether you have internet access"
                )
                sys.exit(3)
        if os.path.exists(opt.web_app_dir) and os.path.isdir(opt.web_app_dir):
            ret = subprocess.Popen(
                ["git", "stash"], cwd=opt.web_app_dir, shell=False
            ).wait()
            if ret != 0:
                logger.error("Failed to clean files locally")
            ret = subprocess.Popen(
                ["git", "pull", "--all"], cwd=opt.web_app_dir, shell=False
            ).wait()
            if ret != 0:
                logger.error("Failed to pull files for serving offline")
            ret = subprocess.Popen(
                ["git", "checkout", "gh-pages"], cwd=opt.web_app_dir, shell=False
            ).wait()
            if ret != 0:
                logger.error("Failed to checkout files from gh-pages")
        if not os.path.exists(opt.web_app_dir):
            logger.info("Downloading files for serving ImJoy locally")
            ret = subprocess.Popen(
                "git clone -b gh-pages --depth 1 "
                "https://github.com/oeway/ImJoy __ImJoy__".split(),
                shell=False,
                cwd=opt.workspace_dir,
            ).wait()
            if ret != 0:
                logger.error(
                    "Failed to download files, "
                    "please check whether you have internet access"
                )
                sys.exit(4)

    return opt
