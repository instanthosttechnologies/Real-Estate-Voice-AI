@echo off
setlocal EnableExtensions

REM BrainMagic RealEstate Voice AI - DEVELOPMENT Launcher
REM Workspace: D:\Brain Magic\RealEstate_Agentic_Voice_AI_Development
REM Branch   : enhancement/voice-ai-development
REM Backend  : http://127.0.0.1:8001
REM Frontend : http://localhost:3001
REM Database : realestate_ai_dev (ISOLATED)

if /I "%~1"=="backend" goto :backend
if /I "%~1"=="frontend" goto :frontend

set "ROOT=%~dp0"
if not exist "%ROOT%backend\app\main.py" (
  echo [ERROR] Could not find backend\app\main.py in %ROOT%
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\package.json" (
  echo [ERROR] Could not find frontend\package.json.
  pause
  exit /b 1
)
if not exist "%ROOT%.venv_nova_sdk\Scripts\python.exe" (
  echo [ERROR] Python SDK environment not found in %ROOT%.venv_nova_sdk
  pause
  exit /b 1
)

cls
echo ===================================================
echo     BrainMagic Voice AI - DEVELOPMENT MODE
echo ===================================================
echo Workspace : %ROOT%
echo Branch    : enhancement/voice-ai-development
echo Website   : http://localhost:3001/login
echo Backend   : http://127.0.0.1:8001
echo Database  : realestate_ai_dev (ISOLATED from Demo)
echo.
echo Voice mode:
echo   [1] SAFE - mock voice, no paid AWS inference
echo   [2] LIVE - real AWS Nova Sonic, incurs AWS charges
echo.
choice /C 12 /N /M "Choose 1 or 2: "
if errorlevel 2 (set "BM_LIVE=1") else (set "BM_LIVE=0")

if "%BM_LIVE%"=="1" (
  set "USE_MOCK_VOICE=False"
  set "LIVE_TEST_APPROVED=True"
  set "LOCAL_VOICE_TEST_MODE=True"
  set "DRY_RUN_TEST_MODE=True"
  echo [OK] Live development mode selected.
) else (
  set "USE_MOCK_VOICE=True"
  set "LIVE_TEST_APPROVED=False"
  set "LOCAL_VOICE_TEST_MODE=True"
  set "DRY_RUN_TEST_MODE=True"
  echo [OK] Safe mock mode selected.
)

start "BrainMagic Dev Backend (Port 8001)" cmd /k call "%~f0" backend
timeout /t 2 /nobreak >nul
start "BrainMagic Dev Frontend (Port 3001)" cmd /k call "%~f0" frontend

echo.
echo Development servers started!
echo Frontend: http://localhost:3001/customer
echo Backend : http://127.0.0.1:8001/docs
echo.
pause
exit /b 0

:backend
cd /d "%~dp0"
echo Starting FastAPI development backend at http://127.0.0.1:8001
"%~dp0.venv_nova_sdk\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --app-dir backend --log-level info
exit /b %errorlevel%

:frontend
cd /d "%~dp0frontend"
echo Starting Next.js development frontend at http://localhost:3001
npx.cmd next dev -p 3001
exit /b %errorlevel%
