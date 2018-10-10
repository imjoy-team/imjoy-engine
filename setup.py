import sys
import subprocess

try:
    subprocess.call(["conda", "-V"])
    CONDA_AVAILABLE = True
except OSError as e:
    if sys.version_info > (3, 0):
        print('WARNING: you are running ImJoy without conda, you may have problem with some plugins.')
    else:
        sys.exit('Sorry, ImJoy plugin engine can only run within a conda environment or at least in Python 3.')

from setuptools import setup, find_packages
requirements = []

try:
    if sys.version_info > (3, 0):
        requirements = ['psutil', 'aiohttp', 'python-socketio', 'requests', 'six', 'websocket-client', 'numpy']
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
except Exception as e:
    # some OSs do not have psutil with pip, try to install the dependencies with conda
    if sys.version_info > (3, 0) and CONDA_AVAILABLE:
        try:
            print('Trying to install package with conda...')
            requirements = ['psutil', 'aiohttp', 'python-socketio', 'requests', 'six', 'websocket-client', 'numpy']
            subprocess.call(["conda", "install"] + requirements)
        except Exception as e:
            print("Failed to install dependencies.")
        finally:
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
