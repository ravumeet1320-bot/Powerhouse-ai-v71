@echo off
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo.
echo NIFTY Powerhouse AI Index Brain v5 is starting on port 8787.
echo Open this computer's LAN IP on your Android/iPhone while on the same Wi-Fi.
echo.
python app.py
