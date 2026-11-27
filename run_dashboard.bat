@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment .venv ...
    py -m venv .venv || python -m venv .venv
    if errorlevel 1 (
        echo Could not create the virtual environment. Is Python installed and on PATH?
        pause
        exit /b 1
    )
    call ".venv\Scripts\python.exe" -m pip install --upgrade pip
    call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Package installation failed. See README - Troubleshooting.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\python.exe" scripts\init_db.py
call ".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
pause
