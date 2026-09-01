@echo off
rem Runs install-shortcut.ps1 without needing the PowerShell execution policy changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-shortcut.ps1" %*
