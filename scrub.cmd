@echo off
rem Runs scrub.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scrub.ps1" %*
