import sys
import pathlib
import subprocess
from setuptools import setup, find_packages

try:
    subprocess.call(["conda", "-V"])
except OSError as e:
    if sys.version_info > (3, 0):
        print('WARNING: you are running ImJoy without conda, you may have problem with some plugins.')
    else:
        sys.exit('Sorry, ImJoy Python Plugin Engine can only run within a conda environment or at least in Python 3.')

requirements = []
if sys.version_info > (3, 0):
    requirements = ['aiohttp', 'python-socketio', 'requests', 'six', 'websocket-client', 'numpy', 'janus', 'pyyaml']

    print('Trying to install psutil with pip...')
    ret = subprocess.Popen(['pip', 'install', 'psutil'], shell=False).wait()
    if ret != 0:
        print('Trying to install psutil with conda...')
        ret2 = subprocess.Popen(["conda", "install", "-y", "psutil"]).wait()
        if ret2 != 0:
            raise Exception('Failed to install psutil, please try to setup an environment with gcc support.')


HERE = pathlib.Path(__file__).parent
README = (HERE / "README.md").read_text()

setup(name='imjoy',
      version='0.7.22',
      description='Python Plugin Engine for ImJoy.io',
      long_description=README,
      long_description_content_type="text/markdown",
      url='http://github.com/oeway/ImJoy-Engine',
      author='Wei OUYANG',
      author_email='oeway007@gmail.com',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      install_requires=requirements,
      zip_safe=False,
      entry_points={
        'console_scripts': [
            'imjoy = imjoy.__main__:main'
        ]
      })
