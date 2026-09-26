"""Separate bundled resources from persistent, writable user data."""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCES = Path(__file__).resolve().parent
BASE = Path(sys.executable).resolve().parent if FROZEN else RESOURCES


def data_directory():
    override = os.environ.get("DUBBING_DATA")
    if override:
        return Path(override).expanduser().resolve()
    if FROZEN:
        local = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / "AppData" / "Local"
        return local / "DubbingStudio" / "data"
    return BASE / "data"


DATA = data_directory()
LIBRARY = Path(os.environ.get("DUBBING_LIBRARY", DATA.parent / "Kursus" if FROZEN else BASE.parent)).resolve()


def configure():
    DATA.mkdir(parents=True, exist_ok=True)
    if FROZEN:
        if "DUBBING_LIBRARY" not in os.environ:
            LIBRARY.mkdir(parents=True, exist_ok=True)
        entries = os.environ.get("PATH", "").split(os.pathsep)
        binary_dir = str(RESOURCES / "bin")
        if binary_dir not in entries:
            os.environ["PATH"] = os.pathsep.join([binary_dir, *entries])
        os.environ.setdefault("HF_HOME", str(DATA / "models" / "huggingface"))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
