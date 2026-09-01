@echo off
rem Runs the monitor behind a system tray icon.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tray.ps1" %*
