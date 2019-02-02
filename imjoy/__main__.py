import sys
import os
import subprocess

def main():
    # add executable path to PATH
    os.environ['PATH'] = os.path.split(sys.executable)[0]  + os.pathsep +  os.environ.get('PATH', '')

    if sys.version_info > (3, 0):
        # running in python 3
        print('Upgrading ImJoy Plugin Engine...')
        ret = subprocess.Popen('pip install -U git+https://github.com/oeway/ImJoy-Engine#egg=imjoy'.split(), shell=False).wait()
        if ret != 0:
            print('Failed to upgrade ImJoy Plugin Engine.')
        from .imjoyPluginEngine import main
        main()
    else:
        # running in python 2
        print('ImJoy needs to run in Python 3.6+, bootstrapping with conda ...')
        imjoy_requirements = ['requests', 'six', 'websocket-client-py3', 'aiohttp', 'git+https://github.com/oeway/ImJoy-Engine#egg=imjoy', 'psutil', "numpy"]
        ret = subprocess.Popen('conda create -y -n imjoy python=3.6'.split(), shell=False).wait()
        if ret == 0:
            print('conda environment is now ready, installing pip requirements and start the engine...')
        else:
            print('conda environment failed to setup, maybe it already exists. Otherwise, please make sure you are running in a conda environment...')
        requirements = imjoy_requirements
        pip_cmd = "pip install -U "+" ".join(requirements)

        if sys.platform == "linux" or sys.platform == "linux2":
            # linux
            process = subprocess.Popen("conda info --json -s | python -c \"import sys, json; print(json.load(sys.stdin)['conda_prefix']);\"", shell=True, stdout=subprocess.PIPE)
            app_path, err = process.communicate()
            conda_activate =  '/bin/bash -c "source '+app_path.decode('ascii').strip()+'/bin/activate {}"'
        elif sys.platform == "darwin":
            # OS X
            conda_activate = "source activate {}"
        elif sys.platform == "win32":
            # Windows...
            conda_activate = "activate {}"
        else:
            conda_activate = "conda activate {}"

        pip_cmd = conda_activate.format(" imjoy && " + pip_cmd + " && python -m imjoy")
        ret = subprocess.Popen(pip_cmd.split(), shell=False).wait()
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
                ret = subprocess.Popen(git_cmd.split(), shell=False).wait()
                if ret != 0:
                    raise Exception('Failed to install git/pip and dependencies with exit code: '+str(ret))
                else:
                    ret = subprocess.Popen(pip_cmd.split(), shell=False).wait()
                    if ret != 0:
                        print('ImJoy failed with exit code: '+str(ret))
                        sys.exit(2)

if __name__ == '__main__':
    main()
