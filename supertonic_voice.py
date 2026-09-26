"""Bundled Supertonic 3 CPU inference. No SDK auto-download or remote synthesis."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from runtime_paths import DATA, RESOURCES

WORKER_FLAG = '--supertonic-worker'
WORKER_SCRIPT = 'supertonic_voice.py'
LABEL = 'Supertonic 3 offline'
VOICES = {f'supertonic-{voice}': f'Supertonic {voice} · {"Pria" if voice[0] == "M" else "Wanita"}'
          for voice in (f'{gender}{number}' for gender in 'MF' for number in range(1, 6))}
LANGUAGES = {
    'en':'Inggris', 'ar':'Arab', 'bg':'Bulgaria', 'cs':'Ceko', 'da':'Denmark', 'de':'Jerman',
    'el':'Yunani', 'es':'Spanyol', 'et':'Estonia', 'fi':'Finlandia', 'fr':'Prancis', 'hi':'Hindi',
    'hu':'Hungaria', 'id':'Indonesia', 'it':'Italia', 'ja':'Jepang', 'ko':'Korea', 'lt':'Lituania',
    'lv':'Latvia', 'nl':'Belanda', 'pl':'Polandia', 'pt':'Portugis', 'ro':'Rumania', 'ru':'Rusia',
    'sk':'Slovakia', 'sl':'Slovenia', 'sv':'Swedia', 'tr':'Turki', 'uk':'Ukraina', 'vi':'Vietnam'
}
FILES = ['onnx/tts.json', 'onnx/unicode_indexer.json', 'onnx/duration_predictor.onnx',
         'onnx/text_encoder.onnx', 'onnx/vector_estimator.onnx', 'onnx/vocoder.onnx',
         *[f'voice_styles/{gender}{number}.json' for gender in 'MF' for number in range(1, 6)]]


def model_directory():
    for root in (DATA / 'models/supertonic-3', RESOURCES / 'models/supertonic-3'):
        if all((root / name).is_file() for name in FILES):
            return root
    return DATA / 'models/supertonic-3'


def ready():
    return (all((model_directory() / name).is_file() for name in FILES)
            and importlib.util.find_spec('onnxruntime') is not None)


def cache_key(text, job):
    return hashlib.sha256(json.dumps(
        [text, job['voice'], job.get('language', 'id'), job['rate'], 'supertonic-3-aafc6e3-steps5-v2'],
        ensure_ascii=False).encode('utf-8')).hexdigest()


def generate(job, update, check):
    from local_voice import generate as run_batch
    return run_batch(job, update, check, backend=sys.modules[__name__])


def worker(manifest_path):
    import os
    import wave
    import numpy as np
    import onnxruntime as ort
    from local_voice import normalize_text, split_text
    from third_party.supertonic.helper import (TextToSpeech, load_cfgs, load_onnx_all,
                                               load_text_processor, load_voice_style)

    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest['voice'] not in VOICES or manifest.get('language', 'id') not in LANGUAGES:
        raise ValueError('Pilihan suara Supertonic tidak valid.')
    model = Path(manifest['model'])
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = min(os.cpu_count() or 2, 4)
    opts.inter_op_num_threads = 1
    opts.enable_mem_pattern = False
    opts.enable_cpu_mem_arena = False
    onnx_dir = str(model / 'onnx')
    sessions = load_onnx_all(onnx_dir, opts, ['CPUExecutionProvider'])
    tts = TextToSpeech(load_cfgs(onnx_dir), load_text_processor(onnx_dir), *sessions)
    style = load_voice_style([str(model / 'voice_styles' / (manifest['voice'].split('-')[1] + '.json'))])
    for index, item in enumerate(manifest['items']):
        target = Path(item['target'])
        temporary = target.with_suffix('.partial.wav')
        try:
            with wave.open(str(temporary), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(tts.sample_rate)
                count = 0
                spoken_text = normalize_text(item['text']) if manifest.get('language', 'id') == 'id' else item['text']
                for text in split_text(spoken_text):
                    samples, duration = tts(text, manifest.get('language', 'id'), style, total_step=5,
                                            speed=1 + manifest['rate'] / 100)
                    samples = samples.reshape(-1)[:round(float(duration[0]) * tts.sample_rate)]
                    if not len(samples) or not np.all(np.isfinite(samples)):
                        raise RuntimeError('Supertonic menghasilkan audio tidak valid.')
                    if count:
                        output.writeframesraw(b'\0\0' * round(.12 * tts.sample_rate))
                    output.writeframesraw((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
                    count += 1
                if not count:
                    raise ValueError('Teks sulih suara kosong.')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        Path(manifest['progress']).write_text(str(index + 1), encoding='ascii')


if __name__ == '__main__':
    worker(sys.argv[1])
