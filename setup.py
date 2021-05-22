"""Set up the imjoy engine package."""
import json
from pathlib import Path

from setuptools import find_packages, setup

DESCRIPTION = (
    "ImJoy Plugin Engine for running Python plugins locally "
    "or remotely from ImJoy.io"
)

try:
    # for Google Colab
    # pylint: disable=unused-import
    import google.colab.output  # noqa: F401

    REQUIREMENTS = ["numpy", "imjoy-rpc>=0.3.0", "imjoy-elfinder"]
except ImportError:
    REQUIREMENTS = [
        "numpy",
        "imjoy-rpc>=0.3.11",
        "pydantic[email]>=1.8.1",
        "typing-extensions>=3.7.4.3",  # required by pydantic
        "python-dotenv>=0.17.0",
        "python-engineio==4.0.0",
        "python-jose==3.2.0",
        "python-socketio[asyncio_client]==5.0.4",
        "pyyaml",
        "fastapi>=0.63.0",
        "uvicorn>=0.13.4",
    ]

ROOT_DIR = Path(__file__).parent.resolve()
README_FILE = ROOT_DIR / "README.md"
LONG_DESCRIPTION = README_FILE.read_text(encoding="utf-8")
VERSION_FILE = ROOT_DIR / "imjoy" / "VERSION"
VERSION = json.loads(VERSION_FILE.read_text())["version"]


setup(
    name="imjoy",
    version=VERSION,
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    url="http://github.com/imjoy-team/ImJoy-Engine",
    author="ImJoy Team",
    author_email="imjoy.team@gmail.com",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.6",
    include_package_data=True,
    install_requires=REQUIREMENTS,
    extras_require={
        "jupyter": ["jupyter>=1.0.0", "ipykernel>=5.1.4", "imjoy-jupyter-extension"],
    },
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
