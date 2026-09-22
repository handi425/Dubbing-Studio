"""Bridge to the user-requested Wikidepia/indonesian-tts model."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv-drat' / 'Scripts' / 'python.exe'
MODEL = ROOT / 'data' / 'models' / 'wikidepia'
SPEAKERS = {'id-ID-ArdiNeural':'ardi', 'id-ID-GadisNeural':'gadis', 'wibowo':'wibowo'}


def ready():
    return PYTHON.is_file() and (MODEL/'.ready').is_file()


def cache_key(text, job):
    return hashlib.sha256(json.dumps([text, job['voice'], job['rate'], job['tts']]).encode()).hexdigest()


def generate(job, update, check):
    from engine import run
    if not ready():
        raise ValueError('Model Wikidepia belum siap. Jalankan PASANG SUARA LOKAL.bat terlebih dahulu.')
    root = Path(job['directory'])
    cache = root/'speech'
    cache.mkdir(exist_ok=True)
    items = []
    for segment in job['segments']:
        path = cache/(cache_key(segment['id'],job)+'.wav')
        if not path.is_file():
            items.append({'text':segment['id'], 'target':str(path)})
    if not items:
        return
    progress = root/'local-progress.txt'
    progress.write_text('0', encoding='ascii')
    manifest = root/'local-request.json'
    manifest.write_text(json.dumps({'items':items,'speaker':SPEAKERS[job['voice']], 'rate':job['rate'],
                                    'progress':str(progress)},ensure_ascii=False),encoding='utf-8')
    latest = -1
    def report():
        nonlocal latest
        check()
        try:
            finished = int(progress.read_text(encoding='ascii'))
        except (ValueError, OSError):
            return
        if finished != latest:
            update(progress=75*finished/len(items), message=f'Suara Wikidepia lokal: {finished}/{len(items)} bagian. Memuat model dapat memerlukan waktu…')
            latest = finished
    run([str(PYTHON),'-X','utf8',str(ROOT/'wikidepia_worker.py'),str(manifest)],report,timeout=14400)
