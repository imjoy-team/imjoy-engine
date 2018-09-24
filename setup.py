import sys
import subprocess

try:
    subprocess.call(["conda", "-V"])
except OSError as e:
    sys.exit('Sorry, ImJoy plugin engine can only run with Anaconda or Miniconda.')

requirements = []
if sys.version_info > (3, 0):
    requirements = ['psutil', 'requests', 'six', 'websocket-client-py3', 'aiohttp', 'numpy']

from setuptools import setup, find_packages
setup(name='imjoy',
      version='0.4.2',
      description='Python plugin engine for ImJoy.io',
      url='http://github.com/oeway/ImJoy',
      author='Wei OUYANG',
      author_email='wei.ouyang@cri-paris.org',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      install_requires=requirements,
      zip_safe=False)
