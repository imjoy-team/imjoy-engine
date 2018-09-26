@setlocal enableextensions
@cd /d "%~dp0"
if not exist %systemdrive%%homepath%\ImJoyApp\Scripts\conda.exe GOTO InstallImJoyApp
powershell -command "& {$env:Path = '%systemdrive%%homepath%\ImJoyApp;%systemdrive%%homepath%\ImJoyApp\Scripts;' + $env:Path ; python -m imjoy}"
IF NOT %ERRORLEVEL%==0 GOTO InstallImJoyApp
pause
goto:eof

:InstallImJoyApp
  Echo Installing ImJoy App...
  pause
  powershell Set-ExecutionPolicy RemoteSigned
  IF NOT %ERRORLEVEL%==0 GOTO RequirePermission
  powershell -file ImJoy.app\Contents\Resources\Windows_Install.ps1
  pause
  goto:eof
:RequirePermission
  Echo Please run this script as Administrator!
  pause
