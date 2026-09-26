$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv-build\Scripts\python.exe')) {
    python -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Python 64-bit dibutuhkan untuk membangun EXE.' }
}
$buildPython = Join-Path $projectRoot '.venv-build\Scripts\python.exe'
& $buildPython -m pip install -r packaging\requirements-build.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Pemasangan dependensi gagal.' }
& $buildPython -c 'from local_translate import ensure_model; ensure_model()'
if ($LASTEXITCODE -ne 0) { throw 'Model terjemahan belum siap.' }
& $buildPython packaging\prepare_notices.py
if ($LASTEXITCODE -ne 0) { throw 'Pengumpulan lisensi gagal.' }
& $buildPython -m PyInstaller --noconfirm DubbingStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'Build EXE gagal.' }
Copy-Item -LiteralPath WINDOWS-EXE.md -Destination dist\PETUNJUK.md
Get-FileHash -LiteralPath dist\DubbingStudio.exe -Algorithm SHA256 | Format-List
