"""Package the ImJoy plugin engine."""
import json
import pathlib

# read version information from file
_here = pathlib.Path(__file__).parent
IMJOY_PACKAGE_DIR = str(_here)
VERSION_INFO = json.loads((_here / "VERSION").read_text())
__version__ = VERSION_INFO["version"]
API_VERSION = VERSION_INFO["api_version"]
