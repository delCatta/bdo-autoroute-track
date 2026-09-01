@echo off
rem Runs setup.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
