"""Download the model assets published by the requested Wikidepia repository."""
import json
import subprocess
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'data' / 'models' / 'wikidepia'
MODEL.mkdir(parents=True, exist_ok=True)
RELEASE = 'https://github.com/Wikidepia/indonesian-tts/releases/download/v1.2/'

for filename in ('checkpoint_1260000-inference.pth', 'config.json', 'speakers.pth'):
    path = MODEL / filename
    if path.exists():
        continue
    temporary = path.with_suffix('.part')
    with requests.get(RELEASE + filename, stream=True, timeout=(15,90)) as response:
        response.raise_for_status()
        size = 0
        with temporary.open('wb') as output:
            for block in response.iter_content(1024*1024):
                output.write(block)
                size += len(block)
                if size % (20*1024*1024) == 0:
                    print(filename, round(size/1024**2), 'MB', flush=True)
    temporary.replace(path)
    print(filename, 'ready', flush=True)

config = json.loads((MODEL/'config.json').read_text(encoding='utf-8'))
config['model_args']['speakers_file'] = str(MODEL/'speakers.pth')
config['speakers_file'] = str(MODEL/'speakers.pth')
(MODEL/'config.local.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
print('Wikidepia model files ready.',flush=True)
python = ROOT/'.venv-drat'/'Scripts'/'python.exe'
if python.exists():
    result = subprocess.run([str(python), '-c', 'import torch, TTS, g2p_id, num2words'], capture_output=True)
    if result.returncode == 0:
        (MODEL/'.ready').write_text('Wikidepia v1.2', encoding='utf-8')
