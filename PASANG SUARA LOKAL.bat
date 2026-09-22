@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
  echo Memasang pengelola Python uv...
  python -m pip install --user uv
  if errorlevel 1 goto failed
  echo Jika uv belum ditemukan, buka ulang launcher setelah folder Scripts Python masuk PATH.
)
if not exist ".venv-drat\Scripts\python.exe" uv venv --python 3.11 .venv-drat
if errorlevel 1 goto failed
uv pip install --python .venv-drat\Scripts\python.exe torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
uv pip install --python .venv-drat\Scripts\python.exe -r requirements-local-tts.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe setup_wikidepia.py
if errorlevel 1 goto failed
echo Model Wikidepia siap. Buka ulang aplikasi untuk memuat pilihan suara lokal.
pause
exit /b 0
:failed
echo Instalasi belum berhasil. Periksa pesan di atas.
pause
exit /b 1
