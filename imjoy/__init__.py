"""Package the ImJoy plugin engine."""
import json
import os
import threading
import time

from imjoy_rpc import api

# read version information from file
IMJOY_PACKAGE_DIR = os.path.dirname(__file__)
with open(os.path.join(IMJOY_PACKAGE_DIR, "VERSION"), "r") as f:
    VERSION_INFO = json.load(f)
    __version__ = VERSION_INFO["version"]
    API_VERSION = VERSION_INFO["api_version"]

_server_thread = None


def _show_elfinder_colab(root_dir="/content", port=8765, height=600, width="100%"):
    from google.colab import output
    from imjoy_elfinder.app import main

    global _server_thread
    if _server_thread is None:

        def start_elfinder():
            global _server_thread
            try:
                main(["--root-dir={}".format(root_dir), "--port={}".format(port)])
            except OSError:
                print("ImJoy-elFinder server already started.")
            _server_thread = thread

        # start imjoy-elfinder server
        thread = threading.Thread(target=start_elfinder)
        thread.start()

    time.sleep(1)
    output.serve_kernel_port_as_iframe(port, height=str(height), width=str(width))


def _show_elfinder_jupyter(url="/elfinder", height=600, width="100%"):
    from IPython import display

    code = """(async (url, width, height, element) => {
        element.appendChild(document.createTextNode(''));
        const iframe = document.createElement('iframe');
        iframe.src = url;
        iframe.height = height;
        iframe.width = width;
        iframe.style.border = 0;
        element.appendChild(iframe);
        })""" + "({url}, {width}, {height}, element[0])".format(
        url=json.dumps(url), width=json.dumps(width), height=json.dumps(height)
    )
    display.display(display.Javascript(code))


def show_elfinder(**kwargs):
    try:
        from google.colab import output

        is_colab = True
    except:
        is_colab = False

    if is_colab:
        _show_elfinder_colab(**kwargs)
    else:
        _show_elfinder_jupyter(**kwargs)
