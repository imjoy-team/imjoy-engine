"""Set up the ImJoy-Engine imjoy package."""
import json
import os

from setuptools import find_packages, setup

DESCRIPTION = (
    "ImJoy Plugin Engine for running Python plugins locally "
    "or remotely from ImJoy.io"
)

try:
    # for Google Colab
    # pylint: disable=unused-import
    import google.colab.output  # noqa: F401

    REQUIREMENTS = [
        "numpy",
        "imjoy-rpc>=0.2.55",
        'pathlib;python_version<"3.4"',
        "imjoy-elfinder",
    ]
except ImportError:
    REQUIREMENTS = [
        "numpy",
        "imjoy-rpc>=0.2.55",
        'pathlib;python_version<"3.4"',
        "imjoy-elfinder[jupyter]",
        "python-socketio[asyncio_client]==5.0.4",
        "python-engineio==4.0.0",
    ]

ROOT_DIR = os.path.dirname(__file__)
with open(os.path.join(ROOT_DIR, "README.md"), "r") as f:
    README = f.read()

with open(os.path.join(ROOT_DIR, "imjoy", "VERSION"), "r") as f:
    VERSION = json.load(f)["version"]

setup(
    name="imjoy",
    version=VERSION,
    description=DESCRIPTION,
    long_description=README,
    long_description_content_type="text/markdown",
    url="http://github.com/imjoy-team/ImJoy-Engine",
    author="ImJoy Team",
    author_email="imjoy.team@gmail.com",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    install_requires=REQUIREMENTS,
    extras_require={
        "jupyter": [
            "jupyter>=1.0.0",
            "ipykernel>=5.1.4",
            "imjoy-jupyter-extension",
        ],
        "socketio": [
            "python-socketio[asyncio_client]",
            "pyyaml",
            "aiohttp",
            "aiohttp_cors",
        ],
    },
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
