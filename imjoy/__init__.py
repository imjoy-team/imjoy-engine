"""Package the ImJoy plugin engine."""
import json
import os
from imjoy.api import *

def start_server(port=9527):
    def on_connected(client_id):
        pass


# read version information from file
IMJOY_PACKAGE_DIR = os.path.dirname(__file__)
with open(os.path.join(IMJOY_PACKAGE_DIR, "VERSION"), "r") as f:
    VERSION_INFO = json.load(f)
    __version__ = VERSION_INFO["version"]
    API_VERSION = VERSION_INFO["api_version"]
