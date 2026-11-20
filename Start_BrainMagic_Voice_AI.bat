@echo off
setlocal EnableExtensions

REM BrainMagic RealEstate Voice AI launcher
REM Save this file in D:\Brain Magic\RealEstate_Agentic_Voice_AI

if /I "%~1"=="backend" goto :backend
if /I "%~1"=="frontend" goto :frontend

set "ROOT=%~dp0"
if not exist "%ROOT%backend\app\main.py" (
  echo [ERROR] Could not find backend\app\main.py in:
  echo         %ROOT%
  echo Copy this BAT into your RealEstate_Agentic_Voice_AI project folder.
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\package.json" (
  echo [ERROR] Could not find frontend\package.json.
  pause
  exit /b 1
)
if not exist "%ROOT%.venv_nova_sdk\Scripts\python.exe" (
  echo [ERROR] Python 3.12 SDK environment not found:
  echo         %ROOT%.venv_nova_sdk\Scripts\python.exe
  pause
  exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm.cmd not found. Install Node.js or add it to PATH.
  pause
  exit /b 1
)

cls
echo ===================================================
echo           BrainMagic Voice AI Launcher
echo ===================================================
echo Project : %ROOT%
echo Website : http://localhost:3000/login
echo Backend : http://127.0.0.1:8000
echo.
echo Voice mode:
echo   [1] SAFE - mock voice, no paid AWS inference
echo   [2] LIVE - real AWS voice, incurs AWS charges
echo.
choice /C 12 /N /M "Choose 1 or 2: "
if errorlevel 2 (set "BM_LIVE=1") else (set "BM_LIVE=0")

REM Explicitly override unsafe values from any inherited environment / backend .env
set "AWS_PROFILE=realestate-nova"
set "AWS_REGION=ap-northeast-1"
set "BEDROCK_MODEL_ID=amazon.nova-2-5-sonic"
set "LOCAL_VOICE_TEST_MODE=False"
set "DIAGNOSTIC_MINIMAL_VOICE_MODE=False"
set "DRY_RUN_TEST_MODE=True"
set "MAX_CONCURRENT_LIVE_SESSIONS=1"
if "%BM_LIVE%"=="1" (
  echo.
  echo WARNING: AWS Bedrock live voice usage costs money.
  choice /C YN /N /M "Confirm LIVE paid voice mode? [Y/N]: "
  if errorlevel 2 (
    echo Cancelled. No servers started.
    pause
    exit /b 0
  )
  set "USE_MOCK_VOICE=False"
  set "LIVE_TEST_APPROVED=True"
  set "DRY_RUN_TEST_MODE=True"
) else (
  set "USE_MOCK_VOICE=True"
  set "LIVE_TEST_APPROVED=False"
  set "DRY_RUN_TEST_MODE=True"
)

echo.
echo Starting FastAPI and Next.js in separate windows...
start "BrainMagic Backend" cmd /k call "%~f0" backend
start "BrainMagic Frontend" cmd /k call "%~f0" frontend

echo.
echo Waiting for Next.js frontend (http://localhost:3000) to respond...
where.exe curl.exe >nul 2>&1
if not errorlevel 1 (
  set "WAIT_SECONDS=0"
  set "MAX_WAIT=30"
  goto :poll_frontend
) else (
  REM Fallback if curl.exe is not available
  timeout /t 8 /nobreak >nul
  goto :open_browser
)

:poll_frontend
curl.exe -s -o nul --connect-timeout 1 http://localhost:3000 >nul 2>&1
if not errorlevel 1 (
  echo Frontend is ready and responding!
  goto :open_browser
)
set /a WAIT_SECONDS+=1
if %WAIT_SECONDS% geq %MAX_WAIT% (
  echo Frontend readiness reached %MAX_WAIT%s timeout limit. Opening browser now...
  goto :open_browser
)
timeout /t 1 /nobreak >nul
goto :poll_frontend

:open_browser
start "" "http://localhost:3000/login"
echo.
echo Login:      http://localhost:3000/login
echo Customer:   http://localhost:3000/customer
echo Admin:      http://localhost:3000/admin
echo Super Owner:http://localhost:3000/super-owner
echo.
echo To stop: press Ctrl+C in both server windows, then close them.
echo Database writes are disabled via DRY_RUN_TEST_MODE=True.
echo To verify saving conversations, use an approved separate database test.
pause
exit /b 0

:backend
cd /d "%~dp0"
echo Starting FastAPI backend at http://127.0.0.1:8000
echo Voice mode: USE_MOCK_VOICE=%USE_MOCK_VOICE% LIVE_TEST_APPROVED=%LIVE_TEST_APPROVED% DRY_RUN_TEST_MODE=%DRY_RUN_TEST_MODE%
"%~dp0.venv_nova_sdk\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend --log-level info
echo.
echo Backend exited. Check errors above.
exit /b %errorlevel%

:frontend
cd /d "%~dp0frontend"
echo Starting Next.js at http://localhost:3000
call npm.cmd run dev
echo.
echo Frontend exited. Check errors above.
exit /b %errorlevel%
