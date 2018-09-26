#!/bin/bash
export PATH=$HOME/ImJoyApp/bin:/anaconda/bin/:$HOME/miniconda/bin/:$HOME/anaconda/bin/:$PATH
condaPath=`which conda`
if [ "$condaPath" = "" ]; then
  if [[ "$OSTYPE" == "linux-gnu" ]]; then
    # Linux
    bash ./Linux_Install.sh || bash ./ImJoy.app/Contents/Resources/Linux_Install.sh
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    # Mac OSX
    bash ./Linux_Install.sh || bash ./ImJoy.app/Contents/Resources/OSX_Install.sh
  elif [[ "$OSTYPE" == "freebsd"* ]]; then
    # ...
    bash ./Linux_Install.sh || bash ./ImJoy.app/Contents/Resources/Linux_Install.sh
  else
    echo "Unsupported OS."
  fi
  $HOME/ImJoyApp/bin/python -m imjoy
else
condaRoot=`dirname "$condaPath"`
$condaRoot/python -m imjoy || pip install git+https://github.com/oeway/ImJoy-Python#egg=imjoy && $condaRoot/python -m imjoy
fi
