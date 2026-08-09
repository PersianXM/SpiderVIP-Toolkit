@echo off
REM Frequency Manager launcher (SpiderVIP monorepo: spidervip/frequency).
cd /d "%~dp0"
echo Installing dependencies (first run only)...
python -m pip install -r requirements.txt >nul 2>&1
echo Stopping any previous instance on port 5000...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" 2>nul
echo Starting Frequency Manager at http://127.0.0.1:5000
start "" "http://127.0.0.1:5000/?ui=polish-v1"
python app.py
pause
