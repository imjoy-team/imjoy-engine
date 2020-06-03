"""Provide main entrypoint."""
import json
import os
import subprocess
import sys

from imjoy.options import parse_cmd_line
from imjoy.utils import read_or_generate_token, write_token


def main():
    """Run main."""
    opt = parse_cmd_line()
    if opt.jupyter:
        sys.argv = sys.argv[:1]
        sys.argc = 1
        from notebook.notebookapp import NotebookApp

        kwargs = {
            "open_browser": False,
            "allow_origin": opt.allow_origin,
            "ip": opt.host,
            "notebook_dir": opt.workspace,
            "port": int(opt.port),
            "tornado_settings": {
                "headers": {
                    "Access-Control-Allow-Origin": opt.allow_origin,
                    "Content-Security-Policy": opt.content_security_policy,
                }
            },
        }

        if not opt.token:
            if not opt.random_token:
                opt.token = read_or_generate_token()
                kwargs["token"] = opt.token
        else:
            kwargs["token"] = opt.token

        app = NotebookApp.instance(**kwargs)
        app.initialize()
        if app.port != int(opt.port):
            print("\nWARNING: using a different port: {}.\n".format(app.port))
        write_token(app.token)
        app._token_generated = True
        app.start()
        return

    if not opt.legacy:
        print(
            "\nNote: We are migrating the backend of the ImJoy Engine to Jupyter, to use it please run `imjoy --jupyter`.\n\nIf you want to use the previous engine, run `imjoy --legacy`, however, please note that it maybe removed soon.\n"
        )
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


if __name__ == "__main__":
    main()
