@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo INSTALL COMPLETE.
echo Double-click START_APP.bat
pause
