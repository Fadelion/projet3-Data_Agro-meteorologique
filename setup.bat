@echo off
setlocal
rem Keep the setup logic in PowerShell; this file is only a cmd.exe entry point.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
exit /b %ERRORLEVEL%
