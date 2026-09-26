"""Run the EXE from another folder with Python/FFmpeg removed from PATH."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[1]
exe = root / "dist" / "DubbingStudio.exe"
workspace = root / "build" / "EXE verification - Bahasa Indonesia"
workspace.mkdir(parents=True, exist_ok=True)
profile = workspace / "Profil Pengguna"
temporary = workspace / "Temp"
temporary.mkdir(exist_ok=True)
env = dict(os.environ, PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
           LOCALAPPDATA=str(profile), TEMP=str(temporary), TMP=str(temporary),
           DUBBING_PORT="18876", DUBBING_SELFTEST_REPORT=str(workspace / "self-test.json"))
for key in ("DUBBING_DATA", "DUBBING_LIBRARY", "PYTHONPATH", "PYTHONHOME", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
    env.pop(key, None)
flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
arguments = [str(exe), "--self-test"]
if "--online-test" in sys.argv:
    arguments.append("--online-test")
with (workspace / "self-test.log").open("w", encoding="utf-8") as log:
    result = subprocess.run(arguments, cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=flags, timeout=600)
report = json.loads((workspace / "self-test.json").read_text(encoding="utf-8"))
assert result.returncode == 0 and report["ok"], report
assert Path(report["data"]) == profile / "DubbingStudio" / "data"
print("Frozen self-test passed:", json.dumps(report["checks"], ensure_ascii=True), flush=True)

base = "http://127.0.0.1:18876"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json", "X-Dubbing-Studio": "1"})
    with opener.open(req, timeout=10) as response:
        return json.load(response)


def start(log):
    process = subprocess.Popen([str(exe), "--no-browser"], cwd=workspace, env=env,
                               stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    try:
        for _ in range(120):
            assert process.poll() is None, "EXE exited before serving HTTP"
            try:
                info = request("/api/info")
                assert info["app_id"] == "dubbing-studio" and info["ffmpeg"]
                return process
            except (OSError, ValueError):
                time.sleep(.5)
        raise RuntimeError("Server startup timed out")
    except BaseException:
        stop(process)
        raise


def stop(process):
    if process.poll() is None:
        subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, check=True)
        process.wait(timeout=20)


with (workspace / "server.log").open("w", encoding="utf-8") as log:
    process = start(log)
    try:
        assert request("/api/jobs") == [], "Release must not include personal jobs"
        for path in ("/", "/static/app.js", "/static/playback.js", "/static/style.css"):
            with opener.open(base + path, timeout=10) as response:
                assert response.status == 200 and len(response.read()) > 100
        course = workspace / "Kursus contoh"
        course.mkdir(exist_ok=True)
        (course / "1. Video.mp4").write_bytes(b"Test index only, not playable media")
        saved = request("/api/playlists", {"folder": str(course)})
        assert saved["count"] == 1
        # A second launch should reuse the running instance and exit successfully.
        duplicate = subprocess.run([str(exe), "--no-browser"], cwd=workspace, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=flags, timeout=60)
        assert duplicate.returncode == 0
    finally:
        stop(process)
    process = start(log)
    try:
        restored = request(f"/api/playlists/{saved['id']}")
        assert restored["count"] == 1 and restored["id"] == saved["id"]
    finally:
        stop(process)

report["checks"].update(http_server=True, second_launch=True, persistent_playlist_after_restart=True,
                       clean_path=True, no_personal_jobs=True)
(workspace / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("PASS: HTTP, assets, clean PATH, repeated launch, and persistence after EXE restart.", flush=True)
