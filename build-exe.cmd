@echo off
rem Runs build-exe.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-exe.ps1" %*
