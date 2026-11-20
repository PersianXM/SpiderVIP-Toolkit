@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Spider VIP - check audio freeze watchdog

where py >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3"
) else (
  set "PY=python"
)

echo.
echo  Checking the audio freeze watchdog on the receiver...
echo  The receiver must be on and connected to the home network.
echo.
%PY% tools\deploy_audio_watch.py status
set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (
  echo  Check finished. "running=" with a number means it is active.
) else (
  echo  Check failed. See the message above.
)
echo.
pause
endlocal & exit /b %EC%
