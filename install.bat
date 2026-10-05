@echo off
setlocal
cd /d "%~dp0"
echo === BEVIMS installer ===
set PY=python
%PY% --version >nul 2>nul || set PY=py -3
%PY% --version >nul 2>nul || (echo [ERROR] Python 3.10+ not found. Install from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" || (echo [ERROR] Python 3.10 or newer is required. & pause & exit /b 1)
if not exist .venv (echo Creating virtual environment... & %PY% -m venv .venv || (echo [ERROR] venv failed & pause & exit /b 1))
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto fail
pip install -r requirements.txt || goto fail
if not exist .env (copy /y .env.example .env >nul & echo Created .env from .env.example)
if not exist data mkdir data
python -m app.database.init_db || goto fail
echo.
echo ===== INSTALLATION COMPLETE =====
echo   1. Run run.bat
echo   2. Open http://127.0.0.1:8000  (run.bat opens it for you)
echo Demo mode starts 5 simulated Bengaluru ambulances automatically.
pause
exit /b 0
:fail
echo [ERROR] Installation failed - see messages above.
pause
exit /b 1
