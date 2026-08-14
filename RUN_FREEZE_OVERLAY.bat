@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title SpiderVIP Freeze Widget
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo.
echo  SpiderVIP Freeze Widget
echo  Native Windows overlay (WebView2) — canvas HTML, Tk-like drag/round
echo.

if not exist "%CD%\tools\freeze_overlay.py" (
  echo [fail] tools\freeze_overlay.py not found.
  echo Run RUN_FREEZE_OVERLAY.bat from the SpiderVIP-Toolkit folder.
  echo.
  pause
  exit /b 1
)

set "PY="
set "UI=--ui"

python -c "import webview" >nul 2>&1
if not errorlevel 1 set "PY=python"

if not defined PY (
  py -3 -c "import webview" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  set "UI=--ui-tk"
  py -3 -c "import tkinter" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  python -c "import sys,tkinter; assert 'WindowsApps' not in sys.executable" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo [fail] Python not found. Install Python 3.9+ with pywebview ^(WebView2^) or tkinter.
  echo   python -m pip install "pywebview>=5"
  echo.
  pause
  exit /b 1
)

echo Using: %PY% %UI%
echo Starting freeze widget...
echo Close the widget window or press Ctrl+C to stop.
echo.
%PY% -u tools\freeze_overlay.py %UI%
set "EC=!ERRORLEVEL!"
echo.
if "!EC!"=="2" echo [fail] Overlay already running. Close the existing widget first.
if not "!EC!"=="0" if not "!EC!"=="2" echo [exit !EC!] Overlay stopped with an error.
echo.
pause
endlocal & exit /b %EC%
