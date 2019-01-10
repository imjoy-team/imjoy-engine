import sys
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
    requirements = ['aiohttp', 'python-socketio', 'requests', 'six', 'websocket-client', 'numpy', 'psutil', 'janus']
try:
    setup(name='imjoy',
          version='0.7.8',
          description='Python Plugin Engine for ImJoy.io',
          url='http://github.com/oeway/ImJoy',
          author='Wei OUYANG',
          author_email='wei.ouyang@cri-paris.org',
          license='MIT',
          packages=find_packages(),
          include_package_data=True,
          install_requires=requirements,
          zip_safe=False)
except Exception as e:
    print('Trying to install psutil with conda...')
    subprocess.call(["conda", "install", "-y", "psutil"])
