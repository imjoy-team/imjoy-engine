import sys
import subprocess

try:
    subprocess.call(["conda", "-V"])
except OSError as e:
    if sys.version_info > (3, 0):
        print('WARNING: you are running ImJoy without conda, you may have problem with some plugins.')
    else:
        sys.exit('Sorry, ImJoy plugin engine can only run within a conda environment or at least in Python 3.')

requirements = []
if sys.version_info > (3, 0):
    requirements = ['aiohttp', 'python-socketio', 'requests', 'six', 'websocket-client-py3', 'psutil', 'numpy']

from setuptools import setup, find_packages
setup(name='imjoy',
      version='0.6.3',
      description='Python plugin engine for ImJoy.io',
      url='http://github.com/oeway/ImJoy',
      author='Wei OUYANG',
      author_email='wei.ouyang@cri-paris.org',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      install_requires=requirements,
      zip_safe=False)
