from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import engine
from course_library import Courses

BASE = Path(__file__).resolve().parent
LIBRARY = Path(os.environ.get("DUBBING_LIBRARY", BASE.parent)).resolve()
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 ** 3
jobs = {}
lock = threading.RLock()
playlist_lock = threading.RLock()
executor = ThreadPoolExecutor(max_workers=1)
cancelled = set()
ACTIVE = {"queued", "preparing", "rendering"}


def save(job):
    path = Path(job["directory"]) / "job.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


for path in DATA.glob("*/job.json"):
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["status"] in ACTIVE:
            job.update(status="interrupted", message="Aplikasi ditutup saat bekerja. Klik Lanjutkan untuk mencoba lagi.")
        jobs[job["id"]] = job
    except (ValueError, KeyError, OSError):
        pass


def public(job, full=True):
    result = {k: copy.deepcopy(v) for k, v in job.items() if k not in {"source", "subtitle", "directory"}}
    if not full:
        result.pop("segments", None)
    return result


def find_job(job_id):
    if job_id not in jobs:
        abort(404, "Proyek tidak ditemukan.")
    return jobs[job_id]


def update(job_id, **values):
    with lock:
        jobs[job_id].update(values)
        save(jobs[job_id])


def work(job_id, phase):
    def check():
        if job_id in cancelled:
            raise engine.Cancelled()
    try:
        check()
        update(job_id, status="preparing" if phase == "prepare" else "rendering", phase=phase, error="", progress=0)
        with lock:
            job = copy.deepcopy(jobs[job_id])
        action = engine.prepare if phase == "prepare" else engine.render
        def publish(**values):
            if phase == "prepare" and job.get("auto_render") and values.get("status") == "review":
                values.update(status="preparing", message="Terjemahan siap. Melanjutkan sulih suara…")
            update(job_id, **values)
        action(job, publish, check)
        if phase == "prepare" and job.get("auto_render"):
            check()
            update(job_id, status="rendering", phase="render", progress=0)
            with lock:
                job = copy.deepcopy(jobs[job_id])
            engine.render(job, lambda **values: update(job_id, **values), check)
    except engine.Cancelled:
        update(job_id, status="cancelled", message="Proses dibatalkan. Hasil sementara disimpan untuk dicoba kembali.")
    except Exception as error:
        app.logger.exception("Job %s failed", job_id)
        update(job_id, status="error", error=str(error), message="Proses belum berhasil. Periksa pesan di bawah, lalu coba lagi.")
    finally:
        cancelled.discard(job_id)


def submit(job, phase):
    cancelled.discard(job["id"])
    job.update(status="queued", phase=phase, progress=0, message="Menunggu giliran…", error="")
    save(job)
    executor.submit(work, job["id"], phase)


def associated_subtitle(video):
    stem = re.sub(r"^CHP\s+\d+\s+", "", video.stem, flags=re.I)
    for name in (video.stem, stem):
        for extension in (".vtt", ".srt"):
            candidate = video.with_name(name + extension)
            if candidate.is_file():
                return candidate
    return None


def library_items():
    result = []
    candidates = []
    for directory, dirs, files in os.walk(LIBRARY):
        dirs[:] = [name for name in dirs if (Path(directory) / name).resolve() != BASE
                   and not name.startswith(".")]
        candidates.extend(Path(directory) / name for name in files if Path(name).suffix.lower() in engine.VIDEO_EXTENSIONS)
    for path in candidates:
        if path.is_file() and path.suffix.lower() in engine.VIDEO_EXTENSIONS and not path.is_relative_to(BASE):
            resolved = path.resolve()
            if not resolved.is_relative_to(LIBRARY):
                continue
            subtitle = associated_subtitle(path)
            result.append({"path": path.relative_to(LIBRARY).as_posix(), "name": path.stem,
                           "folder": path.parent.relative_to(LIBRARY).as_posix(),
                           "size_mb": round(path.stat().st_size / 1024 ** 2, 1), "subtitle": bool(subtitle)})
    def natural(item):
        return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", item["path"])]
    return sorted(result, key=natural)


def options(data):
    voice = data.get("voice", "id-ID-ArdiNeural")
    tts = data.get("tts", "edge")
    translator = data.get("translator", "local")
    model = data.get("model", "base.en")
    rate = int(data.get("rate", 0))
    volume = float(data.get("original_volume", 0))
    output_mode = data.get("output_mode", "video")
    if output_mode not in {"video", "audio"}:
        raise ValueError("Format hasil tidak valid.")
    if voice not in engine.VOICES or tts not in {"edge", "azure", "wikidepia"} or translator not in {"local", "google", "azure"}:
        raise ValueError("Pilihan suara atau layanan tidak valid.")
    if model not in {"tiny.en", "base.en", "small.en"} or not -30 <= rate <= 30 or not 0 <= volume <= 0.5:
        raise ValueError("Pilihan model, kecepatan, atau volume tidak valid.")
    if translator == "azure" and not os.environ.get("AZURE_TRANSLATOR_KEY"):
        raise ValueError("Microsoft Translator membutuhkan AZURE_TRANSLATOR_KEY pada environment Windows.")
    if tts == "azure" and not (os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")):
        raise ValueError("Azure Speech membutuhkan AZURE_SPEECH_KEY dan AZURE_SPEECH_REGION pada environment Windows.")
    if tts == "wikidepia":
        from wikidepia import ready
        if not ready():
            raise ValueError("Wikidepia belum siap. Jalankan PASANG SUARA LOKAL.bat terlebih dahulu.")
    return dict(voice=voice, tts=tts, translator=translator, model=model, rate=rate, original_volume=volume, output_mode=output_mode)


@app.before_request
def local_only():
    # Do not allow arbitrary web pages to issue requests against this local server.
    if request.host.split(":")[0] not in {"localhost", "127.0.0.1"}:
        abort(403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            abort(403)
        if request.headers.get("X-Dubbing-Studio") != "1":
            abort(403)


@app.errorhandler(Exception)
def error_response(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return jsonify(error=str(error)), 400
    app.logger.exception("Request failed")
    return jsonify(error="Terjadi kesalahan aplikasi. Lihat log untuk detail."), 500


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/info")
def info():
    import shutil
    from wikidepia import ready
    return jsonify(voices=engine.VOICES, ffmpeg=bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
                   wikidepia=ready(),
                   azure_speech=bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")),
                   azure_translator=bool(os.environ.get("AZURE_TRANSLATOR_KEY")))


@app.get("/api/library")
def library():
    return jsonify(library_items())


def courses():
    return Courses(DATA, LIBRARY, BASE, associated_subtitle)


@app.get("/api/playlists")
def list_playlists():
    with playlist_lock:
        return jsonify(courses().list())


@app.get("/api/playlists/<course_id>")
def get_playlist(course_id):
    with playlist_lock:
        return jsonify(courses().detail(course_id))


@app.post("/api/playlists")
def add_playlist():
    data = request.get_json()
    with playlist_lock:
        if data.get("kind") == "upload":
            result = courses().begin_upload(data.get("name", ""), data.get("source_folder", ""))
        else:
            result = courses().add_local(data.get("folder", ""), data.get("name", ""))
        return jsonify(result), 201


@app.post("/api/playlists/<course_id>/files")
def upload_playlist_file(course_id):
    uploaded = request.files.get("file")
    if not uploaded:
        raise ValueError("Pilih file yang akan diimpor.")
    with playlist_lock:
        courses().upload(course_id, request.form.get("path", ""), uploaded)
    return jsonify(ok=True)


@app.post("/api/playlists/<course_id>/finish")
def finish_playlist(course_id):
    with playlist_lock:
        return jsonify(courses().finish(course_id))


@app.post("/api/playlists/<course_id>/refresh")
def refresh_playlist(course_id):
    with playlist_lock:
        return jsonify(courses().detail(course_id, refresh=True))


@app.get("/api/jobs")
def list_jobs():
    with lock:
        return jsonify([public(job, False) for job in reversed(list(jobs.values()))])


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    with lock:
        return jsonify(public(find_job(job_id)))


@app.post("/api/jobs")
@app.post("/api/jobs/batch")
def create():
    data = request.form
    selected = options(data)
    sources = []
    paths = list(dict.fromkeys(data.getlist("library_path")))
    uploads = request.files.getlist("video")
    if paths and uploads:
        raise ValueError("Pilih video dari pustaka atau unggahan, bukan keduanya.")
    for value in paths:
        source, subtitle = courses().resolve(data.get("playlist_id", "default"), value)
        sources.append((source, None, subtitle))
    for upload in uploads:
        if not upload.filename or Path(upload.filename).suffix.lower() not in engine.VIDEO_EXTENSIONS:
            raise ValueError("Semua unggahan harus berupa video MP4, MKV, MOV, WEBM, AVI, atau M4V.")
        sources.append((None, upload, None))
    if not sources:
        raise ValueError("Pilih atau unggah video MP4, MKV, MOV, WEBM, AVI, atau M4V.")
    supplied = request.files.get("subtitle")
    if supplied and len(sources) > 1:
        raise ValueError("Subtitle manual hanya untuk satu video. Untuk banyak video, gunakan subtitle pustaka atau transkripsi otomatis.")
    if supplied and Path(supplied.filename).suffix.lower() not in {".srt", ".vtt"}:
        raise ValueError("Subtitle harus berformat SRT atau VTT.")
    subtitle_bytes = supplied.read(5 * 1024 ** 2 + 1) if supplied else None
    if subtitle_bytes is not None:
        if len(subtitle_bytes) > 5 * 1024 ** 2:
            raise ValueError("Ukuran subtitle maksimal 5 MB.")
    batch_id = uuid.uuid4().hex if len(sources) > 1 else None
    created, directories = [], []
    try:
        for source, upload, subtitle in sources:
            job_id = uuid.uuid4().hex
            directory = DATA / job_id
            directory.mkdir()
            directories.append(directory)
            title = Path(upload.filename).stem if upload else source.stem
            if upload:
                source = directory / ("input" + Path(upload.filename).suffix.lower())
                upload.save(source)
            if supplied:
                subtitle = directory / ("input" + Path(supplied.filename).suffix.lower())
                subtitle.write_bytes(subtitle_bytes)
            created.append(dict(id=job_id, title=title, source=str(source), subtitle=str(subtitle) if subtitle else None,
                                directory=str(directory), segments=[], warnings=[], batch_id=batch_id,
                                playlist_id=data.get("playlist_id", "default") if paths else None,
                                auto_render=bool(batch_id), **selected))
    except Exception:
        for directory in directories:
            # Only remove fresh staging directories created by this request.
            if directory.resolve().parent == DATA.resolve():
                shutil.rmtree(directory)
        raise
    with lock:
        for job in created:
            jobs[job["id"]] = job
            submit(job, "prepare")
        result = {"jobs": [public(job) for job in created]}
        return jsonify(result if request.path.endswith("/batch") or len(created) > 1 else public(created[0])), 201


@app.post("/api/jobs/<job_id>/save")
def save_edits(job_id):
    with lock:
        job = find_job(job_id)
        if job["status"] in ACTIVE or not job["segments"]:
            abort(409, "Teks belum bisa diedit saat proses berjalan.")
        data = request.get_json()
        texts = data.get("translations")
        if not isinstance(texts, list) or len(texts) != len(job["segments"]):
            raise ValueError("Jumlah bagian terjemahan tidak sesuai.")
        if any(not isinstance(t, str) or not t.strip() or len(t) > 4000 for t in texts):
            raise ValueError("Setiap terjemahan harus berisi 1–4.000 karakter.")
        selected = options({**job, **{k: data[k] for k in ("voice", "rate", "original_volume", "tts") if k in data}})
        for segment, translated in zip(job["segments"], texts):
            segment["id"] = translated.strip()
        job.update(selected)
        job.update(status="review", message="Perubahan disimpan. Buat ulang hasil untuk menerapkan perubahan.")
        engine.write_subtitles(job["segments"], Path(job["directory"]))
        save(job)
        return jsonify(public(job))


@app.post("/api/jobs/<job_id>/render")
def render(job_id):
    with lock:
        job = find_job(job_id)
        if job["status"] in ACTIVE or not job["segments"]:
            abort(409, "Tunggu sampai terjemahan siap.")
        submit(job, "render")
        return jsonify(public(job))


@app.post("/api/jobs/<job_id>/retry")
def retry_job(job_id):
    with lock:
        job = find_job(job_id)
        if job["status"] in ACTIVE:
            abort(409, "Proses masih berjalan.")
        submit(job, "render" if job.get("phase") == "render" and job["segments"] else "prepare")
        return jsonify(public(job))


@app.post("/api/jobs/<job_id>/cancel")
def cancel(job_id):
    with lock:
        job = find_job(job_id)
        if job["status"] in ACTIVE:
            cancelled.add(job_id)
            update(job_id, message="Membatalkan setelah operasi saat ini selesai…")
    return jsonify(ok=True)


@app.get("/api/jobs/<job_id>/files/<name>")
def file(job_id, name):
    with lock:
        job = find_job(job_id)
        allowed = {"hasil.mp4", "hasil.mp3", "subtitle.id.srt", "subtitle.en.srt", "subtitle.id.vtt", "subtitle.en.vtt", "transkrip.txt"}
        if name not in allowed:
            abort(404)
        path = Path(job["directory"]) / name
        if not path.is_file():
            abort(404)
        if name in {"hasil.mp4", "hasil.mp3"} and job["status"] != "done":
            abort(409, "Buat hasil kembali untuk menerapkan perubahan terbaru.")
        filename = (secure_filename(job["title"]) or "video") + "-" + name
    return send_file(path, as_attachment=request.args.get("download") == "1", download_name=filename, conditional=True)


if __name__ == "__main__":
    import webbrowser
    from waitress import serve
    port = int(os.environ.get("DUBBING_PORT", "8765"))
    if "--no-browser" not in __import__("sys").argv:
        threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Dubbing Studio siap: http://127.0.0.1:{port}", flush=True)
    serve(app, host="127.0.0.1", port=port, threads=6,
          max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
