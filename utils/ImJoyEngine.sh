#!/bin/bash
export PATH_BK=$PATH
export DEFAULT_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# detect conda in ImJoyEngine

export PATH=$HOME/ImJoyApp/bin:$DEFAULT_PATH
condaPath=`which conda`

export PATH=$HOME/ImJoyApp/bin:$PATH_BK:$DEFAULT_PATH
if [ "$condaPath" = "" ]; then
  if [ -d "$HOME/ImJoyApp" ]; then
    DATE_WITH_TIME=`date "+%Y%m%d-%H%M%S"`
    mv "$HOME/ImJoyApp" "$HOME/ImJoyApp-$DATE_WITH_TIME"
  fi
  if [[ "$OSTYPE" == "linux-gnu" ]]; then
    # Linux
    bash ./Linux_Install.sh || bash ./ImJoyEngine.app/Contents/Resources/Linux_Install.sh
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    # Mac OSX
    bash ./OSX_Install.sh || bash ./ImJoyEngine.app/Contents/Resources/OSX_Install.sh
  elif [[ "$OSTYPE" == "freebsd"* ]]; then
    # ...
    bash ./Linux_Install.sh || bash ./ImJoyEngine.app/Contents/Resources/Linux_Install.sh
  else
    echo "Unsupported OS."
  fi
  # detect conda in ImJoyApp
  export PATH=$HOME/ImJoyApp/bin:$DEFAULT_PATH
  condaPath=`which conda`
  if [ "$condaPath" = "" ]; then
    echo "Failed to install Miniconda for ImJoy."
  fi
  export PATH=$HOME/ImJoyApp/bin:$PATH_BK:$DEFAULT_PATH
  $HOME/ImJoyApp/bin/python -m imjoy "$@"
else
condaRoot=`dirname "$condaPath"`
$condaRoot/python -m imjoy "$@" || pip install imjoy --upgrade && $condaRoot/python -m imjoy "$@"
fi
