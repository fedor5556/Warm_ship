@echo off
cd /d "%~dp0"
TITLE Warm Ship - ferry ticket monitor

:: Self-heal: venv-only, NEVER fall back to system Python (server python is
:: uv-managed / PEP 668 and refuses pip install)
if not exist "venv\Scripts\python.exe" (
    echo [INFO] venv missing - creating it...
    python -m venv venv || py -m venv venv
)
if not exist "venv\Scripts\python.exe" (
    echo [FATAL] Could not create venv. Is Python installed?
    pause
    exit /b 1
)
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"

"%PYTHON_CMD%" -m pip install --upgrade pip
"%PYTHON_CMD%" -m pip install -r requirements.txt || (echo [FATAL] pip failed & pause & exit /b 1)

if not exist logs mkdir logs
if exist logs\runner.stop del logs\runner.stop

:: If the central runner (Admin_hub\runner.py) is alive, hand off to it: it
:: starts bot.py hidden, keeps it alive after crashes, and brings it back
:: after a reboot. Otherwise fall back to the legacy visible-window launch.
powershell -NoProfile -Command "$r = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'runner\.py' }; if ($r) { exit 0 } else { exit 1 }"
if %ERRORLEVEL%==0 goto :runner

echo [WARN] Central runner not detected - legacy visible-window launch.

:: Kill an already-running instance of THIS bot only: folder-path AND script
:: name must both match; admin_bot is exempt. One token = one poller.
echo [INFO] Stopping any existing Warm Ship instance...
powershell -NoProfile -Command "$proj=('%~dp0').ToLower(); Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $c=($_.CommandLine+'').ToLower(); $e=($_.ExecutablePath+'').ToLower(); ($c -notmatch 'admin_bot') -and ($c.Contains($proj) -or $e.Contains($proj)) -and $c.Contains('bot.py') } | ForEach-Object { taskkill /F /PID $_.ProcessId }"
timeout /t 3 /nobreak >nul

echo [LAUNCH] Starting Warm Ship bot...
powershell -NoProfile -Command "& '%PYTHON_CMD%' -u bot.py 2>&1 | Tee-Object -FilePath logs\launcher.log"

echo.
echo [EXIT] Warm Ship stopped. Read any error above, then press a key to close.
pause >nul
exit /b 0

:runner
echo [INFO] Central runner detected - requesting hidden (re)start.
echo start > logs\runner.start
:: plain "exit" (not /b): the Hub starts this bat via `start`, which keeps the
:: console open after the script ends - exit closes the window too.
exit 0
