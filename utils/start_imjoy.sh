#!/bin/bash
export PATH=$HOME/ImJoyApp/bin:/anaconda/bin/:$HOME/miniconda/bin/:$HOME/anaconda/bin/:$PATH
condaPath=`which conda`
if [ "$condaPath" = "" ]; then
bash ./OSX_Install.sh
$HOME/ImJoyApp/python -m imjoy
else
condaRoot=`dirname "$condaPath"`
$condaRoot/python -m imjoy
fi
