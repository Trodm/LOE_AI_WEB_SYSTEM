@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3.12 -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt
cd app
python -m uvicorn web_app:app --host 0.0.0.0 --port 8000
pause
