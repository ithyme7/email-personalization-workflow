@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3.12 launch_web_app.py
) else (
    python launch_web_app.py
)
echo.
echo App stopped. Press any key to close this window.
pause >nul
