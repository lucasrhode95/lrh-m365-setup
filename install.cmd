@echo off
rem Runs install.ps1 with the execution policy relaxed for this one process only,
rem so a downloaded script is not blocked. It changes no machine or user setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 pause
