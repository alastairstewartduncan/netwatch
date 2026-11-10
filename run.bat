@echo off
REM Runs NetWatch from source (installs dependencies the first time).
cd /d "%~dp0"
python -c "import webview, psutil, pystray, PIL" 2>nul || python -m pip install -r requirements.txt
start "" pythonw netwatch.py
