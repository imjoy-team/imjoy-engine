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

Write-Host ("`nInstalling $AppName to "+(get-location).path+"\$InstallDir")


# Download Latest Miniconda Installer
Write-Host "`nDownloading Miniconda Installer...`n"

(New-Object System.Net.WebClient).DownloadFile("https://repo.continuum.io/miniconda/Miniconda3-latest-Windows-x86_64.exe", "$pwd\Miniconda_Install.exe")

# Install Python environment through Miniconda
Write-Host "Installing Miniconda...`n"
Start-Process Miniconda_Install.exe "/S /AddToPath=0 /D=$InstallDir" -Wait

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
Remove-Item "Miniconda_Install.exe"
conda clean -iltp --yes

# Add Entry Point to path

if(Test-Path variable:EntryPoint)
{
    # Move entry-point executable to an isolated folder
    $script_folder = "$InstallDir\PathScripts"
    New-Item $script_folder -type directory | Out-Null
    Move-Item $InstallDir\Scripts\$EntryPoint.exe $script_folder

    # Ask user if they want to update path
    $title = "Update Path"
    $message = "`nDo you want to add the $EntryPoint script to your User PATH?"

    $yes = New-Object System.Management.Automation.Host.ChoiceDescription "&Yes", `
        "Prepends the User PATH variable with the location of the $EntryPoint script"

    $no = New-Object System.Management.Automation.Host.ChoiceDescription "&No", `
        "User PATH is not modified"

    $options = [System.Management.Automation.Host.ChoiceDescription[]]($yes, $no)

    $result = $host.ui.PromptForChoice($title, $message, $options, 0)

    if($result -eq 0)
    {
        # Update the user's path
        $old_path = (Get-ItemProperty -Path HKCU:\Environment).Path
        $new_path = $script_folder + ";" + $old_path
        cmd /c "setx PATH $new_path"
        Set-ItemProperty -Path HKCU:\Environment -Name PATH -Value $new_path
        Write-Host "User PATH has been updated"
        Write-Host "Open a new command prompt to see the change"
    }
    else
    {
        Write-Host "User PATH was not modified.`n"
        Write-Host "You may want to add the $EntryPoint script to your path."
        Write-Host "It is located in: $script_folder`n"
    }
}

# create a shortcut to the desktop
$WshShell = New-Object -comObject WScript.Shell
strDesktop = WshShell.SpecialFolders("Desktop")
$Shortcut = $WshShell.CreateShortcut(strDesktop + "ImJoy Plugin Engine.lnk")
# $Shortcut.IconLocation = "$env:userprofile\ImJoyApp"
$Shortcut.WorkingDirectory = "$env:userprofile"
$Shortcut.TargetPath = "$env:userprofile\ImJoyApp\bin\python.exe"
$Shortcut.Arguments = "-m imjoy"
$Shortcut.Save()

Write-Host "`n$AppName Successfully Installed"

Write-Host "Press any key to continue ..."

$x = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
