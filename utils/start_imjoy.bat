@setlocal enableextensions
@cd /d "%~dp0"
if not exist %systemdrive%%homepath%\ImJoyApp\Scripts\conda.exe GOTO InstallImJoyApp
powershell -command "& {$env:Path = '%systemdrive%%homepath%\ImJoyApp;%systemdrive%%homepath%\ImJoyApp\Scripts;' + $env:Path ; python -m imjoy}"
IF NOT %ERRORLEVEL%==0 GOTO InstallImJoyApp
pause
goto:eof

:InstallImJoyApp
  Echo Installing ImJoy App...
  if exist "%systemdrive%%homepath%\ImJoyApp\" (
    set LOGFILE_DATE=%DATE:~6,4%.%DATE:~3,2%.%DATE:~0,2%
    set LOGFILE_TIME=%TIME:~0,2%.%TIME:~3,2%
    move %systemdrive%%homepath%\ImJoyApp %systemdrive%%homepath%\ImJoyApp-%LOGFILE_DATE%-%LOGFILE_TIME%
  )
  powershell Set-ExecutionPolicy RemoteSigned
  IF NOT %ERRORLEVEL%==0 GOTO RequirePermission
  powershell -ExecutionPolicy Bypass -file ImJoy.app\Contents\Resources\Windows_Install.ps1
  pause
  goto:eof
:RequirePermission
  Echo Please run this script as Administrator!
  pause
