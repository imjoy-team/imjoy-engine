"""Provide utilities that should not be aware of ImJoy engine."""
import copy
import json
import os
import string
import secrets
import sys
import threading
import time
import uuid
import posixpath
from typing import List, Optional
from importlib import import_module

if sys.platform == "win32":
    from ctypes import windll

    def get_drives():
        """Return windows drives."""
        drives = []
        bitmask = windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drives.append(os.path.abspath(letter + ":/"))
            bitmask >>= 1
        return drives


_SERVER_THREAD = None


_os_alt_seps: List[str] = list(
    sep for sep in [os.path.sep, os.path.altsep] if sep is not None and sep != "/"
)


def generate_password(length=20):
    """Generate a password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for i in range(length))


def safe_join(directory: str, *pathnames: str) -> Optional[str]:
    """Safely join zero or more untrusted path components to a base directory.

    This avoids escaping the base directory.
    :param directory: The trusted base directory.
    :param pathnames: The untrusted path components relative to the
        base directory.
    :return: A safe path, otherwise ``None``.

    This function is copied from:
    https://github.com/pallets/werkzeug/blob/fb7ddd89ae3072e4f4002701a643eb247a402b64/src/werkzeug/security.py#L222
    """
    parts = [directory]

    for filename in pathnames:
        if filename != "":
            filename = posixpath.normpath(filename)

        if (
            any(sep in filename for sep in _os_alt_seps)
            or os.path.isabs(filename)
            or filename == ".."
            or filename.startswith("../")
        ):
            raise Exception(
                f"Illegal file path: `{filename}`, "
                "you can only operate within the work directory."
            )

        parts.append(filename)

    return posixpath.join(*parts)


def _show_elfinder_colab(root_dir="/content", port=8765, height=600, width="100%"):
    # pylint: disable=import-error, import-outside-toplevel, no-name-in-module
    from google.colab import output
    from imjoy_elfinder.app import main

    global _SERVER_THREAD  # pylint: disable=global-statement
    if _SERVER_THREAD is None:

        def start_elfinder():
            global _SERVER_THREAD  # pylint: disable=global-statement
            try:
                main([f"--root-dir={root_dir}", f"--port={port}"])
            except OSError:
                print("ImJoy-elFinder server already started.")
            _SERVER_THREAD = thread

        # start imjoy-elfinder server
        thread = threading.Thread(target=start_elfinder)
        thread.start()

    time.sleep(1)
    output.serve_kernel_port_as_iframe(port, height=str(height), width=str(width))


def _show_elfinder_jupyter(url="/elfinder", height=600, width="100%"):
    from IPython import display  # pylint: disable=import-outside-toplevel

    code = (
        """(async (url, width, height, element) => {
        element.appendChild(document.createTextNode(''));
        const iframe = document.createElement('iframe');
        iframe.src = url;
        iframe.height = height;
        iframe.width = width;
        iframe.style.border = 0;
        element.appendChild(iframe);
        })"""
        + f"({json.dumps(url)}, {json.dumps(width)}, {json.dumps(height)}, element[0])"
    )
    display.display(display.Javascript(code))


def show_elfinder(**kwargs):
    """Show elfinder."""
    try:
        # pylint: disable=import-outside-toplevel, unused-import
        from google.colab import output  # noqa: F401

        is_colab = True
    except ImportError:
        is_colab = False

    if is_colab:
        _show_elfinder_colab(**kwargs)
    else:
        _show_elfinder_jupyter(**kwargs)


def read_or_generate_token(token_path=None):
    """Read or generate token."""
    token_path = token_path or os.path.join(os.path.expanduser("~"), ".jupyter_token")
    # read token from file if exists
    try:
        with open(token_path, "r", encoding="utf-8") as fil:
            token = fil.read()
    except FileNotFoundError:
        token = str(uuid.uuid4())
        with open(token_path, "w", encoding="utf-8") as fil:
            fil.write(token)

    return token


def write_token(token, token_path=None):
    """Write token."""
    token_path = token_path or os.path.join(os.path.expanduser("~"), ".jupyter_token")
    with open(token_path, "w", encoding="utf-8") as fil:
        fil.write(token)


def parse_repos(requirements, work_dir):
    """Return a list of repositories from a list of requirements."""
    repos = []
    if isinstance(requirements, list):
        requirements = [str(req) for req in requirements]
        for req in requirements:
            if ":" in req:
                req_parts = req.split(":")
                typ, libs = req_parts[0], ":".join(req_parts[1:])
                typ, libs = typ.strip(), libs.strip()
                libs = [lib.strip() for lib in libs.split(" ") if lib.strip() != ""]
                if typ == "repo" and libs:
                    name = libs[0].split("/")[-1].replace(".git", "")
                    repo = {
                        "url": libs[0],
                        "repo_dir": os.path.join(
                            work_dir, libs[1] if len(libs) > 1 else name
                        ),
                    }
                    repos.append(repo)
    return repos


def console_to_str(string_):
    """From pypa/pip project, pip.backwardwardcompat. License MIT."""
    try:
        return string_.decode(sys.__stdout__.encoding)
    except UnicodeDecodeError:
        return string_.decode("utf_8")
    except AttributeError:  # for tests, #13
        return string_


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


def kill_process(pid, logger=None):
    """Kill process."""
    psutil = get_psutil()
    if psutil is None:
        return
    if logger:
        logger.info("Killing process (pid=%s)", pid)
    try:
        current_process = psutil.Process(pid)
        for proc in current_process.children(recursive=True):
            try:
                if proc.is_running():
                    proc.kill()
            except psutil.NoSuchProcess:
                if logger:
                    logger.info("Subprocess %s has already been killed", pid)
            except Exception as exc:  # pylint: disable=broad-except
                if logger:
                    logger.error(
                        "Failed to kill a subprocess (pid=%s). Error: %s", pid, exc
                    )
        current_process.kill()
        if logger:
            logger.info("Process %s was killed.", pid)
    except psutil.NoSuchProcess:
        if logger:
            logger.info("Process %s has already been killed", pid)
    except Exception as exc:  # pylint: disable=broad-except
        if logger:
            logger.error(
                "Failed to kill a process (pid=%s), "
                "you may want to kill it manually. Error: %s",
                pid,
                exc,
            )


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
