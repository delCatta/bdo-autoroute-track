@echo off
rem Opens the settings window.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0settings.ps1" %*
