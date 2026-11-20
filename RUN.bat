@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SpiderVIP Console
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo.
echo  SpiderVIP Console
echo  http://127.0.0.1:8787/
echo.

where py >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo [fail] Python not found. Install Python 3.9+ and retry.
    echo.
    pause
    exit /b 1
  )
  set "PY=python"
)

for /f "usebackq delims=" %%V in (`%PY% -c "from spidervip._version import __version__; print(__version__)" 2^>nul`) do set "APPVER=%%V"
if defined APPVER (
  echo  Version v%APPVER%
  echo.
)

echo [1/4] Installing deps...
%PY% -m pip install -q flask
if errorlevel 1 (
  echo [warn] pip install failed - continuing anyway
)

echo [2/4] Local package on PYTHONPATH.
echo [3/4] Freeing port 8787 if needed...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" 2>nul

echo [4/4] Starting Console and opening browser...
start "" "http://127.0.0.1:8787/"
echo.
echo Stop with Ctrl+C. Window stays open on exit.
echo.
%PY% -m spidervip.cli console --simulate
set "EC=%ERRORLEVEL%"
echo.
if not "%EC%"=="0" echo [exit %EC%] Console stopped with an error.
if "%EC%"=="0" echo Console stopped.
echo.
pause
endlocal & exit /b %EC%