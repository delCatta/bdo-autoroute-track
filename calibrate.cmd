@echo off
rem Runs calibrate.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0calibrate.ps1" %*
