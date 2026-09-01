@echo off
title DSSP Automation Dashboard
color 0A
echo.
echo  ================================================
echo    DSSP Automation Dashboard
echo  ================================================
echo.
echo  Starting server at http://localhost:5050
echo  Press Ctrl+C to stop.
echo.

:: Change to the folder where this .bat lives
cd /d "%~dp0"

:: Open the dashboard in the default browser after a short delay (2 s)
:: Uses PowerShell Start-Sleep then start so Python has time to bind the port
start "" powershell -windowstyle hidden -command "Start-Sleep 2; Start-Process 'http://localhost:5050'"

:: Launch Python dashboard (blocking)
python dashboard.py

echo.
echo  Server stopped. Press any key to exit.
pause >nul
