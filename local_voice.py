"""Offline Indonesian speech using CPU ONNX Runtime, without PyTorch or a service."""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

from runtime_paths import DATA, FROZEN, RESOURCES

WORKER_FLAG = '--voice-worker'
WORKER_SCRIPT = 'local_voice.py'
LABEL = 'AI Wikidepia offline'


def model_directory():
    for path in (DATA / 'models/voice-onnx', RESOURCES / 'models/voice-onnx'):
        if all((path / name).is_file() for name in ('voice.onnx', 'voice.json')):
            return path
    return DATA / 'models/voice-onnx'


def ready():
    path = model_directory()
    return (all((path / name).is_file() for name in ('voice.onnx', 'voice.json'))
            and all(importlib.util.find_spec(name) is not None
                    for name in ('onnxruntime', 'g2p_id', 'num2words')))


def cache_key(text, job):
    return hashlib.sha256(json.dumps(
        [text, job['voice'], job['rate'], 'onnx-v1'], ensure_ascii=False).encode('utf-8')).hexdigest()


def generate(job, update, check, backend=None):
    from engine import run
    backend = backend or sys.modules[__name__]
    if not backend.ready():
        raise ValueError('Suara AI offline belum tersedia. Gunakan paket aplikasi dengan model suara ONNX.')
    root = Path(job['directory'])
    cache = root / 'speech'
    cache.mkdir(exist_ok=True)
    items = {}
    for segment in job['segments']:
        check()
        target = cache / (backend.cache_key(segment['id'], job) + '.wav')
        if not target.is_file():
            items[str(target)] = {'text': segment['id'], 'target': str(target)}
    if not items:
        return
    progress = root / 'onnx-progress.txt'
    progress.write_text('0', encoding='ascii')
    manifest = root / 'onnx-request.json'
    manifest.write_text(json.dumps(dict(items=list(items.values()), voice=job['voice'],
                                        rate=job['rate'], progress=str(progress),
                                        language=job.get('language', 'id'),
                                        model=str(backend.model_directory())), ensure_ascii=False), encoding='utf-8')
    latest = -1

    def report():
        nonlocal latest
        check()
        try:
            finished = int(progress.read_text(encoding='ascii'))
        except (OSError, ValueError):
            return
        if finished != latest:
            update(progress=75 * finished / len(items),
                   message=f'Suara {backend.LABEL}: {finished}/{len(items)} bagian…')
            latest = finished

    # Isolated worker releases all model RAM after the batch and can be cancelled.
    command = ([sys.executable, backend.WORKER_FLAG] if FROZEN else
               [sys.executable, '-X', 'utf8', str(RESOURCES / backend.WORKER_SCRIPT)])
    run([*command, str(manifest)], report, timeout=14400)


def normalize_text(text):
    from num2words import num2words
    from decimal import Decimal
    # Indonesian thousands separators and decimal comma, including percentages.
    text = re.sub(r'\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b',
                  lambda m: m[0].replace('.', ''), text)
    text = re.sub(r'-?\d+(?:[.,]\d+)?',
                  lambda m: num2words(Decimal(m[0].replace(',', '.')), lang='id'), text)
    text = text.replace('%', ' persen').replace('&', ' dan ')
    # The upstream pronunciation predictor supports at most 32 letters per word.
    return re.sub(r'[A-Za-z]{32,}',
                  lambda m: ' '.join(m[0][i:i+25] for i in range(0, len(m[0]), 25)), text)


def split_text(text, limit=180):
    """Bound synthesis memory even when the editor contains a long paragraph."""
    for sentence in re.split(r'(?<=[.!?;:])\s+', text.strip()):
        chunk = ''
        for word in sentence.split():
            if chunk and len(chunk) + len(word) + 1 > limit:
                yield chunk
                chunk = ''
            chunk = f'{chunk} {word}'.strip()
        if chunk:
            yield chunk


def encode_phonemes(phonemes, config):
    import unicodedata
    cleaned = re.sub(r'\s+', ' ', unicodedata.normalize('NFC', phonemes).lower())
    vocab = {char: index for index, char in enumerate(config['vocab'])}
    ids = [vocab[char] for char in cleaned if char in vocab]
    if not ids:
        raise ValueError('Teks tidak mengandung pengucapan bahasa Indonesia yang dapat dibuat suara.')
    if config['add_blank']:
        spaced = [config['blank_id']] * (2 * len(ids) + 1)
        spaced[1::2] = ids
        return spaced
    return ids


def worker(manifest_path):
    import os
    import wave
    import numpy as np
    import onnxruntime as ort
    from g2p_id import G2P

    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    model = Path(manifest['model'])
    config = json.loads((model / 'voice.json').read_text(encoding='utf-8'))
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(os.cpu_count() or 2, 4)
    options.inter_op_num_threads = 1
    options.enable_mem_pattern = False
    options.enable_cpu_mem_arena = False
    session = ort.InferenceSession(str(model / 'voice.onnx'), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    phonemizer = G2P()
    progress = Path(manifest['progress'])
    scales = np.array([config['noise_scale'], 1 / (1 + manifest['rate'] / 100),
                       config['noise_scale_dp']], dtype=np.float32)
    for index, item in enumerate(manifest['items']):
        target = Path(item['target'])
        temporary = target.with_suffix('.partial.wav')
        try:
            with wave.open(str(temporary), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(config['sample_rate'])
                chunks = 0
                for text in split_text(normalize_text(item['text'])):
                    ids = encode_phonemes(phonemizer(text), config)
                    samples = session.run(['output'], {
                        'input': np.array([ids], dtype=np.int64),
                        'input_lengths': np.array([len(ids)], dtype=np.int64),
                        'scales': scales,
                        'sid': np.array([config['speakers'][manifest['voice']]], dtype=np.int64),
                    })[0].reshape(-1)
                    if not len(samples) or not np.all(np.isfinite(samples)):
                        raise RuntimeError('Model suara menghasilkan audio tidak valid.')
                    if chunks:
                        output.writeframesraw(b'\0\0' * round(.12 * config['sample_rate']))
                    # Match Coqui's save_wav gain, with bounded 16-bit output.
                    gain = 32767 / max(.01, float(np.max(np.abs(samples))))
                    output.writeframesraw(np.clip(samples * gain, -32767, 32767).astype('<i2').tobytes())
                    chunks += 1
                if not chunks:
                    raise ValueError('Teks sulih suara kosong.')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        progress.write_text(str(index + 1), encoding='ascii')


if __name__ == '__main__':
    worker(sys.argv[1])
