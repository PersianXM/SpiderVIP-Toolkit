@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Spider VIP - install audio freeze watchdog

where py >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3"
) else (
  set "PY=python"
)

echo.
echo  Installing the audio freeze watchdog on the receiver...
echo  The receiver must be on and connected to the home network.
echo.
%PY% tools\deploy_audio_watch.py install
set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (
  echo  DONE. The receiver is patched.
) else (
  echo  NOT DONE. See the message above, then try again.
)
echo.
pause
endlocal & exit /b %EC%
