"""Provide main entrypoint."""
import importlib
import json
import os
import subprocess
import sys

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

    pip_available = True
    try:
        import distutils.spawn

        if distutils.spawn.find_executable("git") is None:
            if not opt.freeze and conda_available:
                print("git not found, trying to install with conda")
                # try to install git
                ret = subprocess.Popen(
                    "conda install -y git".split(), shell=False
                ).wait()
                if ret != 0:
                    raise Exception(
                        "Failed to install git/pip and dependencies "
                        "with exit code: {}".format(ret)
                    )
            elif not opt.freeze:
                print(
                    "git not found, unable to install it because conda is not available"
                )

        if distutils.spawn.find_executable("pip") is None:
            pip_available = False
            if not opt.freeze and conda_available:
                print("pip not found, trying to install pip with conda")
                # try to install pip
                ret = subprocess.Popen(
                    "conda install -y pip".split(), shell=False
                ).wait()
                if ret != 0:
                    raise Exception(
                        "Failed to install git/pip and dependencies "
                        "with exit code: {}".format(ret)
                    )
                else:
                    pip_available = True
            elif not opt.freeze:
                print(
                    "pip not found, unable to install it because conda is not available"
                )
        else:
            print("Upgrading pip...")
            ret = subprocess.Popen(
                "python -m pip install -U pip".split(), shell=False
            ).wait()
            if ret != 0:
                print("Failed to upgrade pip.")
    except Exception as e:
        print("Failed to check or install pip/git, error: {}".format(e))

    try:
        import psutil
    except ImportError:
        if not opt.freeze:
            if pip_available:
                print("Trying to install psutil with pip")
                ret = subprocess.Popen(
                    "python -m pip install psutil".split(),
                    env=os.environ.copy(),
                    shell=False,
                ).wait()
            else:
                ret = 1

            if ret != 0 and conda_available:
                print("Trying to install psutil with conda")
                ret2 = subprocess.Popen(
                    "conda install -y psutil".split(), env=os.environ.copy()
                ).wait()
                if ret2 != 0:
                    print(
                        "WARNING: Failed to install psutil, "
                        "please try to setup an environment with gcc support."
                    )
                else:
                    print("psutil was installed successfully.")
            elif ret != 0:
                print("Failed to install psutil.")

    if sys.version_info > (3, 0):
        if not opt.freeze and pip_available:
            # running in python 3
            print("Upgrading ImJoy Plugin Engine")
            ret = subprocess.Popen(
                "python -m pip install -U imjoy[engine]".split(),
                env=os.environ.copy(),
                shell=False,
            ).wait()
            if ret != 0:
                print("Failed to upgrade ImJoy Plugin Engine")
        elif not opt.freeze:
            print("Failed to upgrade the engine because pip was not found.")

        # reload to use the new version
        import imjoy

        importlib.reload(imjoy)
        from imjoy.engine import run

        run()
    else:
        # running in python 2
        if conda_available:
            print("ImJoy needs to run in Python 3.6+, bootstrapping with conda")
            ret = subprocess.Popen(
                "conda create -y -n imjoy python=3.6 conda".split(),
                env=os.environ.copy(),
                shell=False,
            ).wait()
            if ret == 0:
                print(
                    "conda environment is now ready, "
                    "installing imjoy and starting the engine"
                )
            else:
                print(
                    "conda environment failed to setup, maybe it already exists. "
                    "Otherwise, please make sure you are running in a conda environment"
                )
            pip_cmd = "python -m pip install -U imjoy[engine]"

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

            pip_cmd = conda_activate.format(
                "imjoy && " + pip_cmd + " && python -m imjoy"
            )
            print("Running command: " + pip_cmd)
            ret = subprocess.Popen(pip_cmd, shell=True).wait()
            if ret != 0:
                raise Exception(
                    "Failed to install and start ImJoy, exit code: {}".format(ret)
                )
        else:
            raise Exception(
                "It seems you are trying to run ImJoy Engine in Python 2, but it requires Python 3.6+ (with conda)."
            )


if __name__ == "__main__":
    main()
