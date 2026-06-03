@echo off
echo ================================================
echo   BillerQ AI Assistant — Starting Server
echo ================================================

pip install -r requirements.txt -q

echo.
echo Stopping any old server on port 8001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1

echo.
echo Server starting at: http://127.0.0.1:8001
echo   Login page:       http://127.0.0.1:8001/login
echo Press Ctrl+C to stop.
echo.

cd /d "%~dp0"
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
