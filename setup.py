"""Set up the ImJoy-Engine imjoy package."""
import os
from setuptools import setup, find_packages
import json

DESCRIPTION = (
    "ImJoy Plugin Engine for running Python plugins locally "
    "or remotely from ImJoy.io"
)


WORKER_REQUIREMENTS = [
    "python-engineio==3.9.1",
    "python-socketio[client]==4.4.0",
    "numpy",
    'janus==0.5.0;python_version>"3.3"',
    'pathlib;python_version<"3.4"',
]

REQUIREMENTS = WORKER_REQUIREMENTS + ["jupyter>=1.0.0"]

LEGACY_ENGINE_REQUIREMENTS = ["aiohttp", "aiohttp_cors", "gputil", "pyyaml"]

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
        "engine": LEGACY_ENGINE_REQUIREMENTS,
        "worker": [],
        "jupyter": ["imjoy-elfinder[jupyter]"],
        "jupyter-worker": ["ipykernel>=5.1.4"],
    },
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
