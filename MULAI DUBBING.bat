@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Menyiapkan Python untuk Dubbing Studio...
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import flask, waitress, edge_tts, requests, faster_whisper, sacremoses, subword_nmt" >nul 2>&1
if errorlevel 1 (
  echo Memasang komponen. Koneksi internet diperlukan...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" launch.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Aplikasi belum dapat berjalan. Periksa pesan di atas.
pause
exit /b 1
