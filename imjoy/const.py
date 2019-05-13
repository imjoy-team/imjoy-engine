"""Provide constants for use with the ImJoy engine."""
import json
import pathlib

DEFAULT_REQUIREMENTS_PY2 = ["requests", "six", "websocket-client", "numpy"]
DEFAULT_REQUIREMENTS_PY3 = [*DEFAULT_REQUIREMENTS_PY2, "janus"]
REQ_PSUTIL = ["psutil"]
REQ_PSUTIL_CONDA = ["conda:psutil"]
ENG = "imjoy_engine"
# read version information from file
HERE = pathlib.Path(__file__).parent
VERSION_INFO = json.loads((HERE / "VERSION").read_text())

__version__ = VERSION_INFO["version"]
API_VERSION = VERSION_INFO["api_version"]
NAME_SPACE = "/"
TEMPLATE_SCRIPT = (HERE / "imjoyWorkerTemplate.py").resolve()
