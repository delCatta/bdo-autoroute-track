@echo off
rem Runs run.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
