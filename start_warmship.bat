@echo off
cd /d "%~dp0"
TITLE Warm Ship - ferry ticket monitor

echo ==============================================================
echo      Starting Warm Ship (mostanet.ru ticket monitor)
echo ==============================================================
echo.

:: Self-heal: create the virtual environment if it is missing
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] No virtual environment found - creating one...
    python -m venv .venv
    if not exist ".venv\Scripts\python.exe" py -m venv .venv
)

set "PYTHON_CMD=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    echo [INFO] Virtual environment found.
) else (
    echo [WARNING] Could not create venv! Falling back to system Python.
)
echo.

:: Ensure logs directory exists
if not exist logs mkdir logs

echo [INFO] Checking dependencies...
if exist ".venv\Scripts\python.exe" "%PYTHON_CMD%" -m pip install -r requirements.txt --quiet
echo.

:: Kill any already-running instance (two pollers on one token = Telegram 409)
echo [INFO] Stopping any existing Warm Ship instance...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'Warm ship' -and $_.CommandLine -match 'bot\.py' } | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }"
echo.

echo [LAUNCH] Starting Warm Ship bot...
"%PYTHON_CMD%" -u bot.py

echo.
echo [EXIT] Warm Ship stopped. Read any error above, then press a key to close.
pause >nul
