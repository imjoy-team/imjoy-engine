import sys
import os
import subprocess

if __name__ == '__main__':

    try:
        subprocess.call(["conda", "-V"])
    except OSError as e:
        sys.exit('Sorry, ImJoy plugin engine can only run with Anaconda or Miniconda.')

    if sys.version_info > (3, 0):
        # running in python 3
        try:
            import pkg_resources  # part of setuptools
            version = pkg_resources.require("imjoy")[0].version
            print('ImJoy Python Plugin Engine (version {})'.format(version))
        except:
            pass
        from .pluginEngine import *
    else:
        # running in python 2
        print('ImJoy needs to run in Python 3.6+, bootstrapping with conda ...')
        imjoy_requirements = ['psutil', 'requests', 'six', 'websocket-client-py3', 'aiohttp', 'numpy', 'git+https://github.com/oeway/ImJoy-Python#egg=imjoy']
        ret = subprocess.Popen('conda create -y -n imjoy python=3.6', shell=True).wait()
        if ret == 0:
            print('conda environment is now ready, installing pip requirements and start the engine...')
        else:
            print('conda environment failed to setup, maybe it already exists. Otherwise, please make sure you are running in a conda environment...')
        requirements = imjoy_requirements
        pip_cmd = "pip install -U "+" ".join(requirements)

        if sys.platform == "linux" or sys.platform == "linux2":
            # linux
            command_template = '/bin/bash -c "source {}/bin/activate"'
            conda_activate = command_template.format("$(conda info --json -s | python -c \"import sys, json; print(json.load(sys.stdin)['conda_prefix']);\")") #os.environ['CONDA_PREFIX'])
        elif sys.platform == "darwin":
            # OS X
            conda_activate = "source activate"
        elif sys.platform == "win32":
            # Windows...
            conda_activate = "activate"
        else:
            conda_activate = "conda activate"

        pip_cmd = conda_activate + " imjoy && " + pip_cmd + " && python -m imjoy"
        ret = subprocess.Popen(pip_cmd, shell=True).wait()
        if ret != 0:
            git_cmd = ''
            import distutils.spawn
            if distutils.spawn.find_executable('git') is None:
                git_cmd += " git"
            if distutils.spawn.find_executable('pip') is None:
                git_cmd += " pip"
            if git_cmd != '':
                logger.info('pip command failed, trying to install git and pip...')
                # try to install git and pip
                git_cmd = "conda install -y" + git_cmd
                ret = subprocess.Popen(git_cmd, shell=True).wait()
                if ret != 0:
                    raise Exception('Failed to install git/pip and dependencies with exit code: '+str(ret))
                else:
                    ret = subprocess.Popen(pip_cmd, shell=True).wait()
                    if ret != 0:
                        print('ImJoy failed with exit code: '+str(ret))
                        sys.exit(2)
