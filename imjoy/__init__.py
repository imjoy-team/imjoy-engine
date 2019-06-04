"""Package the ImJoy plugin engine."""
import json
import pathlib

# read version information from file
HERE = pathlib.Path(__file__).parent
IMJOY_PACKAGE_DIR = str(HERE.absolute())
VERSION_INFO = json.loads((HERE / "VERSION").read_text())
__version__ = VERSION_INFO["version"]
API_VERSION = VERSION_INFO["api_version"]
