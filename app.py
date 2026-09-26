from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import threading
import uuid
import tempfile
import zipfile
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import engine
import ai_settings
from ai_settings import protect_secret
from course_library import Courses
from runtime_paths import BASE, DATA, LIBRARY, RESOURCES, configure

configure()
app = Flask(__name__, static_folder=str(RESOURCES / "static"), static_url_path="/static")
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
    from supertonic_voice import LANGUAGES
    result['language_name'] = LANGUAGES.get(result.get('language', 'id'), 'Indonesia')
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
    from local_voice import ready as onnx_ready
    from supertonic_voice import ready as supertonic_ready, VOICES as supertonic_voices
    from supertonic_voice import LANGUAGES
    tts = data.get("tts", default_tts())
    voice = data.get("voice", "supertonic-M1" if tts == "supertonic" else "id-ID-ArdiNeural")
    translator = data.get("translator", "local")
    model = data.get("model", "base.en")
    rate = int(data.get("rate", 0))
    volume = float(data.get("original_volume", 0))
    output_mode = data.get("output_mode", "video")
    language = data.get('language', 'id')
    if output_mode not in {"video", "audio"}:
        raise ValueError("Format hasil tidak valid.")
    if voice not in engine.VOICES or tts not in {"edge", "azure", "wikidepia", "onnx", "supertonic"} or translator not in {"local", "google", "azure", "openrouter"}:
        raise ValueError("Pilihan suara atau layanan tidak valid.")
    if (tts == "supertonic") != (voice in supertonic_voices):
        raise ValueError("Pilih suara yang sesuai dengan mesin suara.")
    if language not in LANGUAGES:
        raise ValueError('Bahasa dubbing tidak tersedia.')
    if language != 'id' and (tts != 'supertonic' or translator not in {'local', 'openrouter'}):
        raise ValueError('Bahasa selain Indonesia memerlukan Supertonic dengan penerjemah Lokal atau OpenRouter.')
    if model not in {"tiny.en", "base.en", "small.en"} or not -30 <= rate <= 30 or not 0 <= volume <= 0.5:
        raise ValueError("Pilihan model, kecepatan, atau volume tidak valid.")
    if translator == 'openrouter' and not read_user_settings()['openrouter_key']:
        raise ValueError('Simpan API key OpenRouter di Pengaturan API OpenRouter terlebih dahulu.')
    if translator == "azure" and not os.environ.get("AZURE_TRANSLATOR_KEY"):
        raise ValueError("Microsoft Translator membutuhkan AZURE_TRANSLATOR_KEY pada environment Windows.")
    if tts == "azure" and not (os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")):
        raise ValueError("Azure Speech membutuhkan AZURE_SPEECH_KEY dan AZURE_SPEECH_REGION pada environment Windows.")
    if tts == "wikidepia":
        from wikidepia import ready
        if not ready():
            raise ValueError("Wikidepia belum siap. Jalankan PASANG SUARA LOKAL.bat terlebih dahulu.")
    if tts == "onnx" and not onnx_ready():
        raise ValueError("Suara AI offline belum tersedia. Gunakan paket aplikasi dengan model suara ONNX.")
    if tts == "supertonic" and not supertonic_ready():
        raise ValueError("Supertonic 3 belum tersedia. Jalankan PASANG SUPERTONIC.bat atau gunakan EXE dengan model Supertonic.")
    return dict(voice=voice, tts=tts, translator=translator, language=language, model=model, rate=rate, original_volume=volume, output_mode=output_mode)


def default_tts():
    from supertonic_voice import ready as supertonic_ready
    from local_voice import ready as onnx_ready
    return 'supertonic' if supertonic_ready() else 'onnx' if onnx_ready() else 'edge'


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


@app.after_request
def refresh_ui_assets(response):
    if request.path == '/' or (request.path.startswith('/static/')
                              and request.path.endswith(('.js', '.css'))):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/info")
def info():
    import shutil
    import hashlib
    from wikidepia import ready
    from local_voice import ready as onnx_ready
    from supertonic_voice import ready as supertonic_ready, LANGUAGES
    return jsonify(app_id="dubbing-studio", version="1.0.0",
                   storage_id=hashlib.sha256(str(DATA.resolve()).casefold().encode()).hexdigest(),
                   voices=engine.VOICES, languages=LANGUAGES, default_language='id', ffmpeg=bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
                   wikidepia=ready(),
                   onnx=onnx_ready(), supertonic=supertonic_ready(), default_tts=default_tts(),
                   azure_speech=bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")),
                   azure_translator=bool(os.environ.get("AZURE_TRANSLATOR_KEY")))


def user_settings_path():
    return DATA / 'settings.json'


def read_user_settings():
    return ai_settings.read_user_settings(user_settings_path())


@app.get('/api/settings')
def get_settings():
    settings = read_user_settings()
    return jsonify(openrouter_configured=bool(settings['openrouter_key']),
                   openrouter_model=settings['openrouter_model'])


@app.post('/api/settings')
def set_settings():
    incoming = request.get_json(force=True)
    previous = read_user_settings()
    key = incoming.get('openrouter_key', '')
    if not key:
        key = previous['openrouter_key']
    if not isinstance(key, str) or (key and not key.startswith('sk-or-v1-')):
        raise ValueError('Format kunci OpenRouter tidak valid.')
    model = incoming.get('openrouter_model', previous['openrouter_model'])
    if not isinstance(model, str) or (model != 'openrouter/free' and not re.fullmatch(r'[\w.-]+/[\w.-]+:free', model)):
        raise ValueError('Pilih model gratis OpenRouter yang valid.')
    target = user_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    stored_key = {'openrouter_key_dpapi': protect_secret(key)} if key and os.name == 'nt' else {'openrouter_key': key}
    temporary.write_text(json.dumps({**stored_key, 'openrouter_model': model}), encoding='utf-8')
    temporary.replace(target)
    return jsonify(openrouter_configured=bool(key), openrouter_model=model)


@app.get('/api/openrouter/models')
def openrouter_models():
    try:
        response = requests.get('https://openrouter.ai/api/v1/models', timeout=(10, 30))
        response.raise_for_status()
        models = response.json().get('data', [])
        free = [{'id': item['id'], 'name': item.get('name', item['id'])} for item in models
                if item.get('id', '').endswith(':free')
                and item.get('pricing', {}).get('prompt') in ('0', 0)
                and item.get('pricing', {}).get('completion') in ('0', 0)
                and 'text' in item.get('architecture', {}).get('output_modalities', ['text'])]
        free.sort(key=lambda item: item['name'].casefold())
        return jsonify([{'id': 'openrouter/free', 'name': 'OpenRouter Free · otomatis'}, *free])
    except requests.RequestException:
        return jsonify([{'id': 'openrouter/free', 'name': 'OpenRouter Free · otomatis'}])


@app.post('/api/jobs/<job_id>/grammar')
def grammar_batch(job_id):
    from grammar_ai import correct_items
    data = request.get_json()
    items = data.get('items') if isinstance(data, dict) else None
    with lock:
        job = find_job(job_id)
        if job['status'] in ACTIVE or not job.get('segments'):
            abort(409, 'Teks belum siap diperiksa.')
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise ValueError('Kirim 1 sampai 8 bagian per permintaan grammar.')
        indices = set()
        for item in items:
            if (not isinstance(item, dict) or type(item.get('index')) is not int
                    or not 0 <= item['index'] < len(job['segments'])
                    or item['index'] in indices or not isinstance(item.get('text'), str)
                    or not item['text'].strip() or len(item['text']) > 4000):
                raise ValueError('Bagian grammar tidak valid.')
            indices.add(item['index'])
        if sum(len(item['text']) for item in items) > 8000:
            raise ValueError('Teks per permintaan grammar terlalu panjang.')
        language = job.get('language', 'id')
        settings = read_user_settings()
    return jsonify(items=correct_items(items, language, settings))


@app.post('/api/jobs/<job_id>/improve/<int:index>')
def improve_segment(job_id, index):
    from grammar_ai import correct_items
    with lock:
        job = find_job(job_id)
        if job['status'] in ACTIVE or not job.get('segments') or not 0 <= index < len(job['segments']):
            abort(409, 'Teks belum siap diperbaiki.')
        data = request.get_json(silent=True) or {}
        text = data.get('text', job['segments'][index]['id'])
        if not isinstance(text, str) or not text.strip() or len(text)>4000:
            raise ValueError('Teks grammar tidak valid.')
        language = job.get('language', 'id')
        settings = read_user_settings()
    result = correct_items([{'index':index, 'text':text}], language, settings)[0]
    return jsonify(text=result['text'], warning=result['warning'])


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
        result = courses().detail(course_id)
    result["results"] = playlist_results(course_id)
    return jsonify(result)


@app.delete('/api/playlists/<course_id>')
def delete_playlist(course_id):
    if course_id == 'default':
        abort(400, 'Playlist pustaka utama tidak dapat dihapus.')
    with playlist_lock:
        course = courses().read(course_id)
        directory = courses().directory(course_id).resolve()
        if directory.parent != (DATA / 'playlists').resolve():
            abort(400, 'Lokasi playlist tidak valid.')
        shutil.rmtree(directory)
    return jsonify(ok=True)


def playlist_results(course_id):
    root = Path(courses().read(course_id)["root"]).resolve()
    with lock:
        completed = [dict(id=job["id"], source=job.get("source", ""), directory=job["directory"],
                          mode=job.get("output_mode", "video"))
                     for job in jobs.values() if job.get("status") == "done" and job.get("source")]
    latest = {}
    for job in completed:
        source = Path(job["source"]).resolve()
        if not source.is_relative_to(root):
            continue
        relative = source.relative_to(root).as_posix()
        filename = "hasil.mp3" if job["mode"] == "audio" else "hasil.mp4"
        output = Path(job["directory"]) / filename
        try:
            stamp = output.stat().st_mtime_ns
            if not output.is_file() or output.stat().st_size == 0:
                continue
        except OSError:
            continue
        key = (relative, job["mode"])
        if key not in latest or stamp > latest[key][0]:
            base = f"/api/jobs/{job['id']}"
            latest[key] = (stamp, dict(job_id=job["id"], mode=job["mode"],
                                      media_url=f"{base}/files/{filename}?v={stamp}",
                                      download_url=f"{base}/files/{filename}?download=1",
                                      source_url=f"{base}/source", source_available=source.is_file()))
    result = {}
    for (relative, mode), (_, media) in sorted(latest.items()):
        result.setdefault(relative, []).append(media)
    return result


@app.get("/api/playlists/<course_id>/results")
def get_playlist_results(course_id):
    return jsonify(playlist_results(course_id))


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
        result = courses().detail(course_id, refresh=True)
    result["results"] = playlist_results(course_id)
    return jsonify(result)


@app.get("/api/jobs")
def list_jobs():
    with lock:
        return jsonify([public(job, False) for job in reversed(list(jobs.values()))])


@app.get('/api/history')
def paginated_history():
    from itertools import islice
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
    except (ValueError, TypeError):
        raise ValueError('Nomor halaman tidak valid.')
    if page < 1 or page_size not in {10, 20, 50}:
        raise ValueError('Pilihan halaman tidak valid.')
    with lock:
        total = len(jobs)
        pages = max(1, math.ceil(total / page_size))
        page = min(page, pages)
        start = (page - 1) * page_size
        items = [history_item(job) for job in islice(reversed(jobs.values()), start, start + page_size)]
    return jsonify(items=items, total=total, page=page, pages=pages, page_size=page_size)


def history_item(job):
    item = public(job, False)
    item['media'] = None
    mode = job.get('output_mode', 'video')
    filename = 'hasil.mp3' if mode == 'audio' else 'hasil.mp4'
    path = Path(job.get('directory', '')) / filename
    if job.get('status') == 'done' and path.is_file() and path.stat().st_size:
        base = f"/api/jobs/{job['id']}"
        item['media'] = dict(mode=mode, media_url=f'{base}/files/{filename}',
            download_url=f'{base}/files/{filename}?download=1', source_url=f'{base}/source',
            source_available=Path(job.get('source', '')).is_file())
    return item


def read_watchlists():
    path = DATA / 'watch-playlists.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def save_watchlists(items):
    path = DATA / 'watch-playlists.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def watchlist_public(playlist):
    result = copy.deepcopy(playlist)
    result['items'] = [history_item(jobs[job_id]) if job_id in jobs else
        dict(id=job_id, title='Proyek telah dihapus', status='missing', media=None)
        for job_id in playlist['job_ids']]
    return result


@app.get('/api/watch-playlists')
def list_watchlists():
    with lock:
        return jsonify([watchlist_public(item) for item in read_watchlists()])


@app.post('/api/watch-playlists')
@app.post('/api/watch-playlists/<playlist_id>')
def write_watchlist(playlist_id=None):
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError('Data playlist tidak valid.')
    with lock:
        playlists = read_watchlists()
        playlist = next((item for item in playlists if item['id'] == playlist_id), None)
        if playlist_id and playlist is None:
            abort(404, 'Playlist tidak ditemukan.')
        name = data.get('name', playlist['name'] if playlist else '')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValueError('Nama playlist harus berisi 1 sampai 120 karakter.')
        adding = data.get('job_ids', [])
        removing = data.get('remove_ids', [])
        if any(not isinstance(ids, list) or len(ids) > 1000 or
               any(not isinstance(value, str) for value in ids) for ids in (adding, removing)):
            raise ValueError('Pilihan proyek tidak valid.')
        if not playlist and not adding:
            raise ValueError('Pilih minimal satu hasil dari History.')
        for job_id in adding:
            if not history_item(find_job(job_id))['media']:
                raise ValueError('Playlist hanya menerima proyek dengan hasil yang sudah selesai dan tersedia.')
        ids = list(dict.fromkeys((playlist['job_ids'] if playlist else []) + adding))
        ids = [job_id for job_id in ids if job_id not in removing]
        if len(ids) > 1000:
            raise ValueError('Maksimal 1000 hasil dalam satu playlist.')
        if playlist is None:
            playlist = dict(id=uuid.uuid4().hex)
            playlists.append(playlist)
        playlist.update(name=name.strip(), job_ids=ids)
        save_watchlists(playlists)
        return jsonify(watchlist_public(playlist))


@app.delete('/api/watch-playlists/<playlist_id>')
def delete_watchlist(playlist_id):
    with lock:
        playlists = read_watchlists()
        remaining = [item for item in playlists if item['id'] != playlist_id]
        if len(remaining) == len(playlists):
            abort(404, 'Playlist tidak ditemukan.')
        save_watchlists(remaining)
    return jsonify(ok=True)


@app.get('/api/watch-playlists/<playlist_id>/download')
def download_watchlist(playlist_id):
    with lock:
        playlist = next((item for item in read_watchlists() if item['id'] == playlist_id), None)
        if playlist is None:
            abort(404, 'Playlist tidak ditemukan.')
        files = []
        for index, job_id in enumerate(playlist['job_ids'], 1):
            job = jobs.get(job_id)
            if not job or not history_item(job)['media']:
                continue
            extension = 'mp3' if job.get('output_mode') == 'audio' else 'mp4'
            title = (secure_filename(job['title']) or 'video')[:120]
            files.append((Path(job['directory']) / f'hasil.{extension}',
                          f'{index:04d}-{title}.{extension}'))
        if not files:
            abort(409, 'Tidak ada hasil tersedia untuk diunduh dalam playlist ini.')
        name = (secure_filename(playlist['name']) or 'playlist')[:120] + '.zip'
    archive = tempfile.TemporaryFile(mode='w+b')
    try:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for path, member in files:
                bundle.write(path, member)
        size = archive.tell()
        archive.seek(0)
        response = send_file(archive, mimetype='application/zip', as_attachment=True,
                             download_name=name, conditional=False)
        response.content_length = size
        response.call_on_close(archive.close)
        return response
    except OSError:
        archive.close()
        abort(409, 'File hasil berubah atau ZIP tidak dapat dibuat. Muat ulang playlist dan coba lagi.')
    except Exception:
        archive.close()
        raise


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    with lock:
        return jsonify(public(find_job(job_id)))


@app.delete('/api/jobs/<job_id>')
def delete_job(job_id):
    with lock:
        job = find_job(job_id)
        if job['status'] in ACTIVE:
            abort(409, 'Batalkan atau tunggu proses ini sebelum menghapus proyek.')
        directory = Path(job['directory']).resolve()
        if directory.parent != DATA.resolve():
            abort(400, 'Lokasi proyek tidak valid.')
        shutil.rmtree(directory)
        jobs.pop(job_id, None)
        playlists = read_watchlists()
        for playlist in playlists:
            playlist['job_ids'] = [value for value in playlist['job_ids'] if value != job_id]
        if playlists:
            save_watchlists(playlists)
    return jsonify(ok=True)


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
        selected = options({**job, **{k: data[k] for k in ("voice", "rate", "original_volume", "tts", "language", "translator") if k in data}})
        for segment, translated in zip(job["segments"], texts):
            segment["id"] = translated.strip()
        job.update(selected)
        job.update(status="review", message="Perubahan disimpan. Buat ulang hasil untuk menerapkan perubahan.")
        engine.write_subtitles(job["segments"], Path(job["directory"]), job.get('language', 'id'))
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
        from supertonic_voice import LANGUAGES
        allowed = {"hasil.mp4", "hasil.mp3", "subtitle.en.srt", "subtitle.en.vtt", "transkrip.txt"}
        allowed.update(f'subtitle.{code}.{ext}' for code in LANGUAGES for ext in ('srt', 'vtt'))
        if name not in allowed:
            abort(404)
        path = Path(job["directory"]) / name
        if not path.is_file():
            abort(404)
        if name in {"hasil.mp4", "hasil.mp3"} and job["status"] != "done":
            abort(409, "Buat hasil kembali untuk menerapkan perubahan terbaru.")
        filename = (secure_filename(job["title"]) or "video") + "-" + name
    return send_file(path, as_attachment=request.args.get("download") == "1", download_name=filename, conditional=True)


@app.get("/api/jobs/<job_id>/source")
def source_video(job_id):
    with lock:
        job = find_job(job_id)
        if job.get("status") != "done" or job.get("output_mode") != "audio":
            abort(409, "Pemutaran bersama tersedia setelah audio dubbing selesai.")
        path = Path(job["source"])
        if not path.is_file() or path.suffix.lower() not in engine.VIDEO_EXTENSIONS:
            abort(404, "Video asli tidak tersedia. Sambungkan drive atau kembalikan folder sumber.")
    mimetype = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
                ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}[path.suffix.lower()]
    return send_file(path, mimetype=mimetype, conditional=True)


if __name__ == "__main__":
    import webbrowser
    from waitress import serve
    port = int(os.environ.get("DUBBING_PORT", "8765"))
    if "--no-browser" not in __import__("sys").argv:
        threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"Dubbing Studio siap: http://127.0.0.1:{port}", flush=True)
    serve(app, host="127.0.0.1", port=port, threads=6,
          max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
