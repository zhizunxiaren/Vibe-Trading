@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_web_ui.ps1" %*
if errorlevel 1 (
  echo.
  echo Startup failed. Press any key to close this window.
  pause >nul
)
