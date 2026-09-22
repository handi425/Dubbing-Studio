"""Manual integration check using a short excerpt from the user's course."""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine

base = Path(__file__).resolve().parents[1]
source = base.parent / '2. Fundamentals' / 'CHP 1 1. Introduction to Harmonic Trading.mp4'
directory = base / 'data' / 'demo-input'
directory.mkdir(exist_ok=True)
video = directory / 'Contoh dubbing kursus - 31 detik.mp4'
engine.run(['ffmpeg','-y','-v','error','-i',str(source),'-t','31','-c:v','libx264','-preset','fast','-crf','21','-c:a','aac',str(video)])
segments = [s for s in engine.read_subtitles(source.with_name('1. Introduction to Harmonic Trading.vtt')) if s['end'] <= 31]
engine.write_subtitles(segments, directory)
with video.open('rb') as media, (directory/'subtitle.en.srt').open('rb') as subtitle:
    response = requests.post('http://127.0.0.1:8765/api/jobs', headers={'X-Dubbing-Studio':'1'},
        data={'translator':'local'}, files={'video':(video.name,media,'video/mp4'), 'subtitle':('source.srt',subtitle)}, timeout=60)
response.raise_for_status()
job_id = response.json()['id']
(directory/'job-id.txt').write_text(job_id)
for _ in range(180):
    job = requests.get(f'http://127.0.0.1:8765/api/jobs/{job_id}',timeout=10).json()
    print(job['status'], job.get('progress'), flush=True)
    if job['status'] not in {'queued','preparing'}:
        print(json.dumps(job,ensure_ascii=True))
        if job['status'] != 'review':
            raise SystemExit(1)
        break
    time.sleep(2)
