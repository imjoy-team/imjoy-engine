import sys
py_version = sys.version
if not py_version.startswith('3') or not 'Anaconda' in py_version :
    sys.exit('Sorry, ImJoy plugin engine can only run with Anaconda(Python 3.6+).')

from setuptools import setup, find_packages
setup(name='imjoy',
      version='0.1.8',
      description='Python plugin engine for ImJoy.io',
      url='http://github.com/oeway/ImJoy',
      author='Wei OUYANG',
      author_email='wei.ouyang@cri-paris.org',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      install_requires=[
          'requests',
          'gevent',
          'python-socketio',
          'aiohttp',
          'six',
          'websocket-client-py3'
      ],
      zip_safe=False)
