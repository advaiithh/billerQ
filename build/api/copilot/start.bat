@echo off
echo ================================================
echo  BillerQ AI Copilot v4.0 - Backend Server
echo ================================================
echo.
echo Starting server on http://localhost:8001
echo.
echo  Health:     http://localhost:8001/health
echo  DB Status:  http://localhost:8001/db/status
echo  Analytics:  http://localhost:8001/analytics
echo.
echo Tip: Copy .env.example to .env and fill in your values.
echo.
cd /d "%~dp0"
python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
pause