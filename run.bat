@echo off
cd /d "%~dp0"

echo ================================================
echo   BillerQ AI Assistant — Starting Server
echo ================================================

pip install -r requirements.txt -q

echo.
echo Stopping previous BillerQ servers...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,8001,8002 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

set PORT=8000
python -c "import socket; s=socket.socket(); r=s.connect_ex(('127.0.0.1',8000)); s.close(); exit(0 if r==0 else 1)" >nul 2>&1
if %ERRORLEVEL%==0 (
  echo WARNING: Port 8000 is in use by an OLD server ^(shows chat, not login^).
  echo          Using port 8002 instead. Restart your PC to free port 8000.
  set PORT=8002
)

echo.
echo Open in browser:  http://127.0.0.1:%PORT%
echo Login / Signup:    http://127.0.0.1:%PORT%/login
echo.
echo Press Ctrl+C to stop.
echo.

uvicorn main:app --host 127.0.0.1 --port %PORT% --reload
