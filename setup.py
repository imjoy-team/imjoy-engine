"""Set up the ImJoy-Engine imjoy package."""
import os
from setuptools import setup, find_packages
import json

DESCRIPTION = (
    "ImJoy Plugin Engine for running Python plugins locally "
    "or remotely from ImJoy.io"
)

try:
    # for Google Colab
    import google.colab.output

    REQUIREMENTS = [
        "numpy",
        "imjoy-rpc>=0.2.21",
        'pathlib;python_version<"3.4"',
    ]
except:
    REQUIREMENTS = [
        "numpy",
        "imjoy-rpc>=0.2.21",
        'pathlib;python_version<"3.4"',
        "jupyter>=1.0.0",
        "imjoy-elfinder[jupyter]",
        "ipykernel>=5.1.4",
        "imjoy-jupyter-extension",
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
    extras_require={},
    zip_safe=False,
    entry_points={"console_scripts": ["imjoy = imjoy.__main__:main"]},
)
