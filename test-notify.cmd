@echo off
rem Runs test-notify.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-notify.ps1" %*
