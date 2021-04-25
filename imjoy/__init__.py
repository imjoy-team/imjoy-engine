"""Package the ImJoy plugin engine."""
import json
import os

from imjoy_rpc import *  # noqa F401, F403
from imjoy_rpc import __all__ as imjoy_rpc_all

# read version information from file
IMJOY_PACKAGE_DIR = os.path.dirname(__file__)
with open(os.path.join(IMJOY_PACKAGE_DIR, "VERSION"), "r") as f:
    VERSION_INFO = json.load(f)
    __version__ = VERSION_INFO["version"]

__all__ = imjoy_rpc_all
