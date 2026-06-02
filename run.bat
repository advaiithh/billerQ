@echo off
echo ================================================
echo   BillerQ AI Assistant — Starting Server
echo ================================================

REM Install dependencies if needed
pip install -r requirements.txt

echo.
echo Server starting at: http://localhost:8000
echo Press Ctrl+C to stop.
echo.

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
