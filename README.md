 [![Build Status](https://travis-ci.com/oeway/ImJoy-Engine.svg?branch=master)](https://travis-ci.com/oeway/ImJoy-Engine) ![ENGINE_VERSION](https://img.shields.io/badge/dynamic/json.svg?color=success&label=imjoy%20engine&prefix=v&query=version&url=https%3A%2F%2Fraw.githubusercontent.com%2Foeway%2FImJoy-Engine%2Fmaster%2FVERSION) ![PyPI](https://img.shields.io/pypi/v/imjoy.svg?style=popout)  ![API_VERSION](https://img.shields.io/badge/dynamic/json.svg?color=success&label=api%20version&prefix=v&query=api_version&url=https%3A%2F%2Fraw.githubusercontent.com%2Foeway%2FImJoy-Engine%2Fmaster%2FVERSION) ![GitHub](https://img.shields.io/github/license/oeway/ImJoy-Engine.svg)
# ImJoy Plugin Engine
The plugin engine used for running python plugins in ImJoy (https://imjoy.io).

## Installation (Desktop App)

If you want to use the plugin engine from a desktop environment, download the latest ImJoy-App from [here](https://github.com/oeway/ImJoy-App/releases). Follow the instructions according to different operating systems.

You will get an executable file for starting the Plugin Engine.

## Installation (Linux servers/clusters)

For using it through a command line interface on a Linux host, run this command in your terminal to install the plugin engine:
```bash
wget https://raw.githubusercontent.com/oeway/ImJoy-Engine/master/utils/Linux_Install.sh  -O - | bash
```

NOTE: When you run the script above, it will first download and install Miniconda3 into `$HOME/ImJoyApp`, it may take considerably amount of space. If you want to uninstall it, run `rm -rf $HOME/ImJoyApp`.  

To start the plugin engine, run:
```
export PATH=~/ImJoyApp/bin:$PATH
imjoy --host=0.0.0.0 --port=9527 --serve
```

Please notice that if you are trying to use ImJoy Plugin Engine running on a remote server, please use the ImJoy web App served on your server (`http://YOUR_REMOTE_IP:9527`) instead of `https://imjoy.io`. This is because most browser do not allow a web application served throught `https` to connect to a unsecured server (your remote server). Alternatively, you use proxy to enable `https` for the plugin engine, then you will be able to use it with `https://imjoy.io`.


## Manual Installation
  If you are in the following situation:
   1) already have a conda environemnt (Anaconda 3 or Miniconda 3)
   1) want better control over the installation process
   2) having trouble with the installation above

  Please follow the manual installation method below:

  * If you don't have a conda environemnt, download and install [Miniconda with Python 3.7](https://conda.io/miniconda.html) (or [Anaconda with Python 3.7](https://www.anaconda.com/download/) if you prefer a full installation).

  * Start a **Terminal**(Mac and Linux) or **Anaconda Prompt**(Windows), then run the following command:

  ```
  conda -V && pip install -U imjoy
  ```

  * If you encountered any error related to `git` or `pip`, try to run : `conda install -y git pip` before the above command. (Otherwise, please check **FAQs**.)

  To use it after the installation:
  * Run `imjoy` command in a **Terminal** or **Anaconda Prompt**, and keep the window running.

  * Go to https://imjoy.io, connect to the plugin engine. For the first time, you will be asked to fill a token generated by the plugin engine from the previous step. Once connected, you can start to run python plugin through the plugin engine.

## Upgrading

Normally, the Plugin Engine will upgrade itself when it starts.
In case you have problem with starting or upgrading the App, try to manually upgrade it by running the following command in a **Terminal**(Mac and Linux) or **Anaconda Prompt**(Windows):
```
PATH=~/ImJoyApp/bin:$PATH pip install -U imjoy
```

## Accessing the ImJoy Engine Conda environment
If you installed the Plugin Engine with the [ImJoyEngine](https://github.com/oeway/ImJoy-Engine/releases), it will setup an Miniconda environment located in `~/ImJoyApp`.

To access the environment on Linux and Mac, you just need to add `~/ImJoyApp/bin` to your `$PATH`:
```
export PATH=~/ImJoyApp/bin:$PATH

# now you can use command such as `imjoy`, `conda`, `pip`, `python` provided from ~/ImJoyApp
imjoy

```
For windows, you can use powershell to add the ImJoyApp to `$env.Path`:
```
$env:Path = '%systemdrive%%homepath%\ImJoyApp;%systemdrive%%homepath%\ImJoyApp\Library\bin;%systemdrive%%homepath%\ImJoyApp\Scripts;' + $env:Path;

# now you can use command such as `imjoy`, `conda`, `pip`, `python` provided from ~/ImJoyApp
imjoy
```

## Uninstall/remove ImJoy Engine
In order to uninstall or remove ImJoy Engine, you need to remove two folders located in your home/user folder: `ImJoyApp` and `ImJoyWorkspace`.

 * `ImJoyApp` contains a Miniconda environemnt and the virtual environemtns used for running ImJoy plugins
 * `ImJoyWorkspace` contains user data for each ImJoy workspace, you may want to backup the data.

On Linux/OSX, you can run the following command:
```
rm -rf $HOME/ImJoyApp   
rm -rf $HOME/ImJoyWorkspace # please backup important data inside this folder
```
On windows, it's typically located in `C:\Users\<CurrentUserName>`, you can remove `ImJoyApp` and `ImJoyWorkspace` manually.

## More details and FAQs in [Docs](https://imjoy.io/docs/#/user_manual)

# Roadmap
You can track the progress of the project here: https://github.com/oeway/ImJoy/projects/2

# Bug report and feature request

Please submit your issue to [ImJoy/issues ](https://github.com/oeway/ImJoy/issues)

## Development

- Development requires Python 3.6, since we use [`black`](https://github.com/ambv/black) for code formatting.

```
  git clone git@github.com:oeway/ImJoy-Engine.git
  # Enter directory.
  cd ImJoy-Engine
  # Install all development requirements and package in development mode.
  pip3 install -r requirements_dev.txt
```

- Run `tox` to run all tests and lint, including checking that `black` doesn't change any files.
