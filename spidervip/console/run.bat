@echo off
REM SpiderVIP Console launcher
cd /d "%~dp0\..\.."
echo Ensuring Flask deps...
python -m pip install flask requests beautifulsoup4 >nul 2>&1
echo Starting SpiderVIP Console at http://127.0.0.1:8787/
start "" "http://127.0.0.1:8787/"
python -m spidervip.cli console --simulate
pause
