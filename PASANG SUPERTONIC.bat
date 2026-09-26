@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -X utf8 setup_supertonic.py
if errorlevel 1 goto failed
echo Supertonic 3 siap. Jalankan MULAI DUBBING.bat.
pause
exit /b 0
:failed
echo Pemasangan gagal. Periksa koneksi internet dan pesan di atas.
pause
exit /b 1
