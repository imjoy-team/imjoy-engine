# For Windows 7, Windows 8, Windows Server 2008 R2 or Windows Server 2012, run the following commands as Administrator:
# x86 (32 bit)
# Open C:\Windows\SysWOW64\cmd.exe
# Run the command powershell Set-ExecutionPolicy RemoteSigned
# x64 (64 bit)
# Open C:\Windows\system32\cmd.exe
# Run the command powershell Set-ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Stop"

# Name of application to install
$AppName="ImJoy"

# Set your project's install directory name here
$InstallDir="$env:userprofile\ImJoyApp"

# Dependencies installed by Conda
# Commend out the next line if no Conda dependencies
$CondaDeps="numpy","scipy", "git" # some examples

# Dependencies installed with pip instead
# Comment out the next line if no PyPi dependencies
$PyPiPackage="git+https://github.com/oeway/ImJoy-Python#egg=imjoy"

# Local packages to install
# Useful if your application is not in PyPi
# Distribute this with a .tar.gz and use this variable
# Comment out the next line if no local package to install
# $LocalPackage="mypackage.tar.gz"

# Entry points to add to the path
# Comment out the next line of no entry point
#   (Though not sure why this script would be useful otherwise)
$EntryPoint=""

Write-Host ("`nInstalling $AppName to "+"$InstallDir")
New-Item $InstallDir -type directory -Force | Out-Null

# Download Latest Miniconda Installer
Write-Host "`nDownloading Miniconda Installer...`n"
(New-Object System.Net.WebClient).DownloadFile("https://repo.continuum.io/miniconda/Miniconda3-latest-Windows-x86_64.exe", "$InstallDir\Miniconda_Install.exe")

Write-Host "Installing Miniconda...`n"
Start-Process $InstallDir\Miniconda_Install.exe "/S /AddToPath=0 /D=$InstallDir" -Wait

$env:Path = "$InstallDir;" + $env:Path

# Install Dependences to the new Python environment
$env:Path = "$InstallDir\Scripts;" + $env:Path

# Make the new python environment completely independent
# Modify the site.py file so that USER_SITE is not imported
$site_program = @"
import site
site_file = site.__file__.replace('.pyc', '.py');
with open(site_file) as fin:
    lines = fin.readlines();
for i,line in enumerate(lines):
    if(line.find('ENABLE_USER_SITE = None') > -1):
        user_site_line = i;
        break;
lines[user_site_line] = 'ENABLE_USER_SITE = False\n'
with open(site_file,'w') as fout:
    fout.writelines(lines)
"@
python -c $site_program

Write-Host "Upgrading PyPi and conda...`n"
pip install pip --upgrade
conda update conda

if(Test-Path variable:CondaDeps)
{
    Write-Host "Installing Conda dependencies...`n"
    conda install $CondaDeps -y
}

if(Test-Path variable:PyPiPackage)
{
    Write-Host "Installing PyPi dependencies...`n"
    pip install $PyPiPackage
}

if(Test-Path variable:LocalPackage)
{
    Write-Host "Installing Local package...`n"
    pip install $LocalPackage
}

# Cleanup
Remove-Item "$InstallDir\Miniconda_Install.exe"
conda clean -iltp --yes

$WorkingDir = Convert-Path .
Copy-Item $WorkingDir\imjoy.ico -Destination $InstallDir\imjoy.ico

# create a shortcut to the desktop
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$Home\Desktop\ImJoy Plugin Engine.lnk")
$Shortcut.IconLocation = "$InstallDir\imjoy.ico, 0"
$Shortcut.WorkingDirectory = "$env:userprofile"
$Shortcut.TargetPath = "$PsHome\powershell.exe"
$Shortcut.Arguments = "-command ""& {`$env:Path = '$InstallDir;$InstallDir\Scripts;' + `$env:Path ; python -m imjoy}"""
$Shortcut.Save()

Write-Host "`n$AppName Successfully Installed"

Write-Host "Press any key to continue ..."

$x = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
