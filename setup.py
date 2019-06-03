"""Set up the ImJoy-Engine imjoy package."""
import os
import sys
import subprocess
from setuptools import setup, find_packages
import json

DESCRIPTION = (
    "ImJoy Plugin Engine for running Python plugins locally "
    "or remotely from ImJoy.io"
)

requirements = ["python-socketio[client]>=4.1.0", "numpy"]

if sys.version_info > (3, 0):
    requirements += ["janus"]

engine_requirements = ["aiohttp", "aiohttp_cors", "gputil", "pyyaml"]

HERE = os.path.normpath(os.path.join(__file__, '..'))
with open(os.path.join(HERE, "README.md"), 'r') as f:
    README = f.read()

with open(os.path.join(HERE, "imjoy", "VERSION"), 'r') as f:
    VERSION = json.load(f)["version"]

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
    extras_require={
        'engine': engine_requirements,
        'worker': [],
    },
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
