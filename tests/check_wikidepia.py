"""Manual test: synthesize real Wikidepia voices and verify readable, nonempty WAV."""
import json
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import engine
import wikidepia

folder = ROOT/'data'/'voice-samples'
folder.mkdir(exist_ok=True)
for speaker in ('ardi','gadis'):
    manifest = folder/f'{speaker}.json'
    target = folder/f'wikidepia-{speaker}.wav'
    manifest.write_text(json.dumps({'items':[{'text':'Selamat datang. Mari belajar pola perdagangan harmonik dalam bahasa Indonesia.',
                                             'target':str(target)}],
        'speaker':speaker,'rate':0,'progress':str(folder/f'{speaker}-progress.txt')},ensure_ascii=False),encoding='utf-8')
    engine.run([str(wikidepia.PYTHON),'-X','utf8',str(ROOT/'wikidepia_worker.py'),str(manifest)],timeout=600)
    with wave.open(str(target),'rb') as audio:
        assert audio.getnframes() > audio.getframerate()
        samples = audio.readframes(audio.getnframes())
        assert any(samples)
    print(speaker, round(engine.media_duration(target),2),'seconds',target.stat().st_size,'bytes',flush=True)
