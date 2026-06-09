@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo   BillerQ AI Assistant — Starting Server
echo ================================================

set "PY=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\python.exe -m pip"
set "MODEL=qwen2.5:7b"

if not exist "%PY%" (
  echo.
  echo Creating virtual environment...
  py -3 -m venv .venv >nul 2>&1
  if errorlevel 1 (
    python -m venv .venv >nul 2>&1
  )
)

if not exist "%PY%" (
  echo.
  echo ERROR: Could not create or find .venv\Scripts\python.exe
  echo Install Python, then run this file again.
  pause
  exit /b 1
)

echo.
echo Installing required Python packages...
%PIP% install --upgrade pip -q
%PIP% install -r requirements.txt -q
if errorlevel 1 (
  echo.
  echo Full requirements install failed. Installing runtime fallback packages...
  echo This avoids the Python 3.13 LangChain/Numpy build issue.
  %PIP% install fastapi==0.111.0 uvicorn==0.29.0 mysql-connector-python==8.4.0 requests==2.32.3 jinja2==3.1.4 python-multipart==0.0.9 bcrypt==4.0.1 openai==1.14.0 -q
  if errorlevel 1 (
    echo.
    echo ERROR: Could not install required runtime packages.
    pause
    exit /b 1
  )
)

echo.
echo Checking Ollama...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  where ollama >nul 2>&1
  if errorlevel 1 (
    echo WARNING: Ollama was not found. AI SQL generation will not work until Ollama is installed and running.
  ) else (
    echo Starting Ollama server...
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -WindowStyle Hidden ollama -ArgumentList 'serve'"
    timeout /t 5 /nobreak >nul
  )
)

where ollama >nul 2>&1
if not errorlevel 1 (
  ollama list | findstr /I "%MODEL%" >nul 2>&1
  if errorlevel 1 (
    echo WARNING: Ollama model %MODEL% is not installed.
    echo          Run this in another terminal if AI generation is needed:
    echo          ollama pull %MODEL%
  )
)

echo.
echo Stopping previous BillerQ servers...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,8001,8002 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

set "PORT="
for %%P in (8000 8001 8002 8003) do (
  "%PY%" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',%%P)); s.close(); raise SystemExit(0 if r else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PORT=%%P"
    goto :port_found
  )
)
:port_found

if "%PORT%"=="" (
  echo.
  echo ERROR: No free port found in 8000, 8001, 8002, or 8003.
  pause
  exit /b 1
)

echo.
echo Open in browser:  http://127.0.0.1:%PORT%
echo Login / Signup:    http://127.0.0.1:%PORT%/login
echo.
echo Press Ctrl+C to stop.
echo.

"%PY%" -m uvicorn main:app --host 127.0.0.1 --port %PORT% --reload
