"""Provide setup function to prepare the engine."""
import json
import os
import shutil
import subprocess
import sys
import uuid

from imjoy.helper import killProcess


def prep_env(opt, logger):
    """Prepare environment."""
    opt.CONDA_AVAILABLE = False
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
        opt.CONDA_AVAILABLE = True
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

    if opt.CONDA_AVAILABLE:
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
    if not opt.CONDA_AVAILABLE and not opt.freeze:
        print(
            "WARNING: `pip install` command may not work, "
            "in that case you may want to add `--freeze`."
        )

    if opt.freeze:
        print(
            "WARNING: you are running the plugin engine with `--freeze`, "
            "this means you need to handle all the plugin requirements yourself."
        )

    opt.WORKSPACE_DIR = os.path.expanduser(opt.workspace)
    if not os.path.exists(opt.WORKSPACE_DIR):
        os.makedirs(opt.WORKSPACE_DIR)

    # read token from file if exists
    try:
        if opt.token is None or opt.token == "":
            with open(os.path.join(opt.WORKSPACE_DIR, ".token"), "r") as fil:
                opt.token = fil.read()
    except Exception:  # pylint: disable=broad-except
        logger.debug("Failed to read token from file")

    try:
        if opt.token is None or opt.token == "":
            opt.token = str(uuid.uuid4())
            with open(os.path.join(opt.WORKSPACE_DIR, ".token"), "w") as fil:
                fil.write(opt.token)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to save .token file: %s", str(exc))

    # try to kill last process
    pid_file = os.path.join(opt.WORKSPACE_DIR, ".pid")
    try:
        if os.path.exists(pid_file):
            with open(pid_file, "r") as fil:
                killProcess(logger, int(fil.read()))
    except Exception:  # pylint: disable=broad-except
        logger.debug("Failed to kill last process")
    try:
        engine_pid = str(os.getpid())
        with open(pid_file, "w") as f:
            f.write(engine_pid)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to save .pid file: %s", str(exc))

    opt.WEB_APP_DIR = os.path.join(opt.WORKSPACE_DIR, "__ImJoy__")
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
                    "Failed to install git, "
                    "please check whether you have internet access."
                )
                sys.exit(3)
        if os.path.exists(opt.WEB_APP_DIR) and os.path.isdir(opt.WEB_APP_DIR):
            ret = subprocess.Popen(
                ["git", "stash"], cwd=opt.WEB_APP_DIR, shell=False
            ).wait()
            if ret != 0:
                print("Failed to clean files locally.")
            ret = subprocess.Popen(
                ["git", "pull", "--all"], cwd=opt.WEB_APP_DIR, shell=False
            ).wait()
            if ret != 0:
                print("Failed to pull files for serving offline.")
            ret = subprocess.Popen(
                ["git", "checkout", "gh-pages"], cwd=opt.WEB_APP_DIR, shell=False
            ).wait()
            if ret != 0:
                print("Failed to checkout files from gh-pages.")
        if not os.path.exists(opt.WEB_APP_DIR):
            print("Downloading files for serving ImJoy locally...")
            ret = subprocess.Popen(
                "git clone -b gh-pages --depth 1 "
                "https://github.com/oeway/ImJoy __ImJoy__".split(),
                shell=False,
                cwd=opt.WORKSPACE_DIR,
            ).wait()
            if ret != 0:
                print(
                    "Failed to download files, "
                    "please check whether you have internet access."
                )
                sys.exit(4)

    return opt
