"""Set up the ImJoy-Engine imjoy package."""
import os
import sys
import pathlib
import subprocess
from setuptools import setup, find_packages
import json

DESCRIPTION = (
    "ImJoy Plugin Engine for running Python plugins locally "
    "or remotely from ImJoy.io"
)

try:
    subprocess.call(["conda", "-V"])
    if os.name == "nt":
        # for fixing CondaHTTPError:
        # https://github.com/conda/conda/issues/6064#issuecomment-458389796
        process = subprocess.Popen(
            ["conda", "info", "--json", "-s"], stdout=subprocess.PIPE
        )
        cout, err = process.communicate()
        conda_prefix = json.loads(cout.decode("ascii"))["conda_prefix"]
        print("Found conda environment: " + conda_prefix)
        os.environ["PATH"] = (
            os.path.join(conda_prefix, "Library", "bin")
            + os.pathsep
            + os.environ["PATH"]
        )
except OSError:
    if sys.version_info > (3, 0):
        print(
            "WARNING: you are running ImJoy without conda, "
            "you may have problem with some plugins."
        )
    else:
        sys.exit(
            "Sorry, ImJoy Python Plugin Engine can only run within a conda environment "
            "or at least in Python 3."
        )

requirements = []
if sys.version_info > (3, 0):
    requirements = [
        "aiohttp",
        "aiohttp_cors",
        "python-socketio",
        "requests",
        "six",
        "websocket-client",
        "numpy",
        "janus",
        "pyyaml",
    ]
    print("Trying to install psutil with pip...")
    ret = subprocess.Popen(
        ["pip", "install", "psutil"], env=os.environ.copy(), shell=False
    ).wait()
    if ret != 0:
        print("Trying to install psutil with conda...")
        ret2 = subprocess.Popen(
            ["conda", "install", "-y", "psutil"], env=os.environ.copy()
        ).wait()
        if ret2 != 0:
            raise Exception(
                "Failed to install psutil, "
                "please try to setup an environment with gcc support."
            )


HERE = pathlib.Path(__file__).parent
README = (HERE / "README.md").read_text()
VERSION = json.loads((HERE / "imjoy" / "VERSION").read_text())["version"]

setup(
    name="imjoy",
    version=VERSION,
    description=DESCRIPTION,
    long_description=README,
    long_description_content_type="text/markdown",
    url="http://github.com/oeway/ImJoy-Engine",
    author="Wei OUYANG",
    author_email="oeway007@gmail.com",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    install_requires=requirements,
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
