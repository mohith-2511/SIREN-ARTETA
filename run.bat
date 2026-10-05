@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Run install.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
if not exist .env copy /y .env.example .env >nul
python -m app.database.init_db
echo Starting BEVIMS on http://127.0.0.1:8000  (press Ctrl+C to stop cleanly)
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
