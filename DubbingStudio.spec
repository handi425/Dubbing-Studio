# Build with .venv-build\Scripts\python.exe -m PyInstaller --noconfirm DubbingStudio.spec
import os
from pathlib import Path
import shutil
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / "static"), "static"),
         (str(root / "build" / "notices"), "licenses"),
         (str(root / "WINDOWS-EXE.md"), ".")]
model = root / "data" / "models" / "translate-en_id-1_9"
if not (model / ".ready").is_file():
    raise RuntimeError("Prepare the local translation model before building")
datas.append((str(model), "models/translate-en_id-1_9"))
binaries = []
for program in ("ffmpeg", "ffprobe"):
    executable = shutil.which(program)
    if not executable:
        raise RuntimeError(f"{program} is required on the build machine")
    binaries.append((executable, "bin"))
for package in ("faster_whisper", "sacremoses", "certifi", "edge_tts"):
    datas += collect_data_files(package)
for package in ("ctranslate2", "onnxruntime", "av"):
    binaries += collect_dynamic_libs(package)
for package in ("faster-whisper", "edge-tts", "sacremoses", "subword-nmt", "Flask"):
    datas += copy_metadata(package, recursive=True)
# App-local MSVC runtime for native AI wheels on PCs without developer tools.
system32 = Path(os.environ["SystemRoot"]) / "System32"
for name in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
             "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll"):
    if (system32 / name).is_file():
        binaries.append((str(system32 / name), "."))

a = Analysis([str(root / "launch.py")], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=["engine", "local_translate", "packaging_selftest", "ctranslate2.models",
                            "tokenizers", "faster_whisper", "onnxruntime", "waitress", "edge_tts"],
             excludes=["torch", "tensorflow", "transformers", "scipy", "matplotlib", "pandas",
                       "ctranslate2.converters", "ctranslate2.specs", "onnxruntime.tools"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="DubbingStudio", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True,
          version=str(root / "packaging" / "version_info.txt"))
