"""Download the pinned official Supertonic 3 assets once; synthesis stays offline."""
import hashlib
import json
from pathlib import Path

import requests

REPO = 'supertone-oss-archive/supertonic-3'
REVISION = 'aafc6e32416a594460b32413efc49d7fe4ce6d46'
FILES = ['LICENSE', 'README.md', 'config.json', 'onnx/tts.json', 'onnx/unicode_indexer.json',
         'onnx/duration_predictor.onnx', 'onnx/text_encoder.onnx',
         'onnx/vector_estimator.onnx', 'onnx/vocoder.onnx',
         *[f'voice_styles/{gender}{number}.json' for gender in 'MF' for number in range(1, 6)]]


def main():
    root = Path(__file__).resolve().parent / 'data/models/supertonic-3'
    response = requests.get(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=30)
    response.raise_for_status()
    assets = {item['rfilename']: item for item in response.json()['siblings']}
    for name in FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        asset = assets[name]
        expected = asset.get('lfs', {}).get('sha256')
        if target.is_file() and target.stat().st_size == asset['size']:
            if not expected or hashlib.sha256(target.read_bytes()).hexdigest() == expected:
                continue
        temporary = target.with_suffix(target.suffix + '.part')
        print(f'Downloading {name}: {asset["size"] / 1024**2:.1f} MiB', flush=True)
        digest = hashlib.sha256()
        with requests.get(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}', stream=True, timeout=(30, 120)) as stream:
            stream.raise_for_status()
            with temporary.open('wb') as output:
                for block in stream.iter_content(1024 * 1024):
                    output.write(block)
                    digest.update(block)
        if temporary.stat().st_size != asset['size'] or (expected and digest.hexdigest() != expected):
            raise RuntimeError(f'Model download verification failed: {name}')
        temporary.replace(target)
    (root / 'PROVENANCE.json').write_text(json.dumps(dict(repo=REPO, revision=REVISION), indent=2), encoding='utf-8')
    print(f'Supertonic 3 ready: {root}', flush=True)


if __name__ == '__main__':
    main()
