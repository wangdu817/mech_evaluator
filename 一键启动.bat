@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo Startup failed. Please review the message above.
    pause
    exit /b 1
)
exit /b 0
