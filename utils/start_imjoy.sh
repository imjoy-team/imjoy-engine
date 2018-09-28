#!/bin/bash
export PATH=$HOME/ImJoyApp/bin:$PATH
condaPath=`which conda`
if [ "$condaPath" = "" ]; then
  if [ -d "$HOME/ImJoyApp" ]; then
    DATE_WITH_TIME=`date "+%Y%m%d-%H%M%S"`
    mv "$HOME/ImJoyApp" "$HOME/ImJoyApp-$DATE_WITH_TIME"
  fi
  if [[ "$OSTYPE" == "linux-gnu" ]]; then
    # Linux
    bash ./Linux_Install.sh || bash ./ImJoy.app/Contents/Resources/Linux_Install.sh
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    # Mac OSX
    bash ./OSX_Install.sh || bash ./ImJoy.app/Contents/Resources/OSX_Install.sh
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
