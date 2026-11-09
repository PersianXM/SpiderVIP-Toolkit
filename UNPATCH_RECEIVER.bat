@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Spider VIP - remove audio freeze watchdog

where py >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3"
) else (
  set "PY=python"
)

echo.
echo  Removing the audio freeze watchdog from the receiver...
echo.
%PY% tools\deploy_audio_watch.py remove
set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (
  echo  DONE. The watchdog is removed.
) else (
  echo  NOT DONE. See the message above, then try again.
)
echo.
pause
endlocal & exit /b %EC%
