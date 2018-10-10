import sys
import subprocess

PSUTIL_INSTALLED = False
try:
    subprocess.call(["conda", "-V"])
    try:
        print('Trying to install psutil with conda...')
        subprocess.call(["conda", "install", "-y", "psutil"])
        PSUTIL_INSTALLED = True
    except Exception as e:
        print("Failed to install psutil.")
except OSError as e:
    if sys.version_info > (3, 0):
        print('WARNING: you are running ImJoy without conda, you may have problem with some plugins.')
    else:
        sys.exit('Sorry, ImJoy plugin engine can only run within a conda environment or at least in Python 3.')

from setuptools import setup, find_packages

requirements = []
if sys.version_info > (3, 0):
    requirements = ['aiohttp', 'python-socketio', 'requests', 'six', 'websocket-client', 'numpy']
    if not PSUTIL_INSTALLED:
        requirements.append("psutil")

setup(name='imjoy',
      version='0.6.7',
      description='Python plugin engine for ImJoy.io',
      url='http://github.com/oeway/ImJoy',
      author='Wei OUYANG',
      author_email='wei.ouyang@cri-paris.org',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      install_requires=requirements,
      zip_safe=False)
