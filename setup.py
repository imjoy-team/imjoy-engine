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

    REQUIREMENTS = ["numpy", "imjoy-rpc>=0.3.26", "imjoy-elfinder"]
except ImportError:
    REQUIREMENTS = [
        "numpy",
        "imjoy-rpc>=0.3.26",
        "pydantic[email]>=1.8.2",
        "typing-extensions>=3.7.4.3",  # required by pydantic
        "aiofiles==0.7.0",
        "jinja2==3.0.1",
        "python-dotenv>=0.17.0",
        "python-engineio==4.0.0",
        "python-jose==3.3.0",
        "python-socketio[asyncio_client]==5.0.4",
        "pyyaml",
        "fastapi>=0.63.0",
        "uvicorn>=0.13.4",
        "fsspec>=2021.10.0",
        "aioboto3>=9.2.0",
    ]

ROOT_DIR = Path(__file__).parent.resolve()
README_FILE = ROOT_DIR / "README.md"
LONG_DESCRIPTION = README_FILE.read_text(encoding="utf-8")
VERSION_FILE = ROOT_DIR / "imjoy" / "VERSION"
VERSION = json.loads(VERSION_FILE.read_text(encoding="utf-8"))["version"]


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
        "server-apps": ["playwright>=1.15.0"],
    },
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
