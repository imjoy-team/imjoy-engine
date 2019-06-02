"""Provide main entrypoint."""
import importlib
import json
import os
import subprocess
import sys

import imjoy
from imjoy.options import parse_cmd_line


def main():
    """Run main."""
    opt = parse_cmd_line()
    if opt.dev:
        print("Running ImJoy Plugin Engine in development mode")
        from .engine import run

        run()
        return

    # add executable path to PATH
    os.environ["PATH"] = (
        os.path.split(sys.executable)[0] + os.pathsep + os.environ.get("PATH", "")
    )
    conda_available = False
    try:
        # for fixing CondaHTTPError:
        # https://github.com/conda/conda/issues/6064#issuecomment-458389796
        process = subprocess.Popen(
            ["conda", "info", "--json", "-s"], stdout=subprocess.PIPE
        )
        cout, _ = process.communicate()
        conda_prefix = json.loads(cout.decode("ascii"))["conda_prefix"]
        print("Found conda environment: {}".format(conda_prefix))
        conda_available = True
        if os.name == "nt":
            os.environ["PATH"] = (
                os.path.join(conda_prefix, "Library", "bin")
                + os.pathsep
                + os.environ["PATH"]
            )
    except OSError:
        if sys.version_info > (3, 0):
            print(
                "WARNING: you are running ImJoy without conda, "
                "you may have problem with some plugins"
            )
        conda_prefix = None

    if sys.version_info > (3, 0):
        # running in python 3
        print("Upgrading ImJoy Plugin Engine")
        ret = subprocess.Popen(
            "pip install -U imjoy".split(), env=os.environ.copy(), shell=False
        ).wait()
        if ret != 0:
            print("Failed to upgrade ImJoy Plugin Engine")

        # reload to use the new version
        importlib.reload(imjoy)
        from imjoy.engine import run

        run()
    else:
        # running in python 2
        print("ImJoy needs to run in Python 3.6+, bootstrapping with conda")
        imjoy_requirements = [
            "aiohttp",
            "aiohttp_cors",
            "imjoy",
            "gputil",
            "psutil",
            "python-socketio[asyncio_client]",
            "pyyaml",
        ]
        ret = subprocess.Popen(
            "conda create -y -n imjoy python=3.6".split(),
            env=os.environ.copy(),
            shell=False,
        ).wait()
        if ret == 0:
            print(
                "conda environment is now ready, "
                "installing pip requirements and starting the engine"
            )
        else:
            print(
                "conda environment failed to setup, maybe it already exists. "
                "Otherwise, please make sure you are running in a conda environment"
            )
        requirements = imjoy_requirements
        pip_cmd = "pip install -U " + " ".join(requirements)

        if conda_available:
            if sys.platform == "linux" or sys.platform == "linux2":
                # linux
                conda_activate = (
                    "/bin/bash -c 'source " + conda_prefix + "/bin/activate {}'"
                )
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

        pip_cmd = conda_activate.format(" imjoy && " + pip_cmd + " && python -m imjoy")
        ret = subprocess.Popen(pip_cmd.split(), shell=False).wait()
        if ret != 0:
            git_cmd = ""
            import distutils.spawn

            if distutils.spawn.find_executable("git") is None:
                git_cmd += " git"
            if distutils.spawn.find_executable("pip") is None:
                git_cmd += " pip"
            if git_cmd != "":
                print("pip command failed, trying to install git and pip")
                # try to install git and pip
                git_cmd = "conda install -y" + git_cmd
                ret = subprocess.Popen(git_cmd.split(), shell=False).wait()
                if ret != 0:
                    raise Exception(
                        "Failed to install git/pip and dependencies "
                        "with exit code: {}".format(ret)
                    )
                ret = subprocess.Popen(pip_cmd.split(), shell=False).wait()
                if ret != 0:
                    print("ImJoy failed with exit code: {}".format(ret))
                    sys.exit(2)


if __name__ == "__main__":
    main()
