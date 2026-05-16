@echo off
setlocal
cd /d "%~dp0"
python launch_web_app.py
echo.
echo App stopped. Press any key to close this window.
pause >nul
