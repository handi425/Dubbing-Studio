import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

import app
import engine


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        for name, value in [('DATA', self.data), ('LIBRARY', self.root), ('jobs', {}), ('cancelled', set())]:
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.app.test_client()
        self.headers = {'X-Dubbing-Studio': '1'}

    def post(self, data, path='/api/jobs/batch'):
        return self.client.post(path, data=data, headers=self.headers)

    def test_multiple_uploads_auto_render_and_independent_downloads(self):
        data = MultiDict([('output_mode', 'audio'), ('video', (io.BytesIO(b'a'), 'one.mp4')),
                          ('video', (io.BytesIO(b'b'), 'two.mkv'))])
        with patch.object(app.executor, 'submit') as submit:
            response = self.post(data)
        self.assertEqual(response.status_code, 201)
        jobs = response.json['jobs']
        self.assertEqual(submit.call_count, 2)
        self.assertEqual(len({j['batch_id'] for j in jobs}), 1)
        for item in jobs:
            self.assertTrue(item['auto_render'])
            self.assertEqual(item['output_mode'], 'audio')
            self.assertEqual(item['status'], 'queued')
        def prepare(job, update, check):
            update(status='review', segments=[dict(start=0, end=1, en='Hello.', id='Halo.')], duration=1)
            self.assertEqual(app.jobs[job['id']]['status'], 'preparing')
        def render(job, update, check):
            self.assertEqual(len(job['segments']), 1)
            (Path(job['directory']) / 'hasil.mp3').write_bytes(b'mp3-test')
            update(status='done')
        with patch.object(engine, 'prepare', prepare), patch.object(engine, 'render', render):
            for item in jobs:
                app.work(item['id'], 'prepare')
        for item in jobs:
            url = f"/api/jobs/{item['id']}/files/hasil.mp3?download=1"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn(item['title'], response.headers['Content-Disposition'])
            response.close()
            app.update(item['id'], status='review')
            self.assertEqual(self.client.get(url).status_code, 409)

    def test_library_batch_subtitles_and_deduplication(self):
        for name in ['one', 'two']:
            (self.root / f'{name}.mp4').write_bytes(b'video')
            (self.root / f'{name}.srt').write_text('subtitle')
        with patch.object(app.executor, 'submit'):
            response = self.post(MultiDict([('library_path', 'one.mp4'), ('library_path', 'two.mp4'), ('library_path', 'one.mp4')]))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json['jobs']), 2)
        for job in app.jobs.values():
            self.assertEqual(Path(job['subtitle']).stem, job['title'])

    def test_invalid_batch_creates_no_jobs(self):
        for extra in [('video', (io.BytesIO(b'x'), 'bad.exe')),
                      ('subtitle', (io.BytesIO(b'x'), 'sub.srt'))]:
            data = MultiDict([('video', (io.BytesIO(b'a'), 'one.mp4')), ('video', (io.BytesIO(b'b'), 'two.mp4')), extra])
            self.assertEqual(self.post(data).status_code, 400)
            self.assertFalse(app.jobs)
            self.assertFalse(list(self.data.iterdir()))
        self.assertEqual(self.post({'output_mode': 'unknown'}).status_code, 400)

    def test_single_video_keeps_review_and_legacy_response(self):
        with patch.object(app.executor, 'submit'):
            response = self.post({'video': (io.BytesIO(b'a'), 'one.mp4')}, '/api/jobs')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json['auto_render'])
        with patch.object(engine, 'prepare', lambda job, update, check: update(status='review')), patch.object(engine, 'render') as render:
            app.work(response.json['id'], 'prepare')
            render.assert_not_called()
        self.assertEqual(app.jobs[response.json['id']]['status'], 'review')

    def test_cancelled_batch_item_does_not_block_next_item(self):
        with patch.object(app.executor, 'submit'):
            response = self.post(MultiDict([('video', (io.BytesIO(b'a'), 'one.mp4')), ('video', (io.BytesIO(b'b'), 'two.mp4'))]))
        first, second = response.json['jobs']
        self.client.post(f"/api/jobs/{first['id']}/cancel", json={}, headers=self.headers)
        with patch.object(engine, 'prepare', lambda job, update, check: update(segments=[{}])), patch.object(engine, 'render', lambda job, update, check: update(status='done')):
            app.work(first['id'], 'prepare')
            app.work(second['id'], 'prepare')
        self.assertEqual(app.jobs[first['id']]['status'], 'cancelled')
        self.assertEqual(app.jobs[second['id']]['status'], 'done')


class AudioMediaTests(unittest.TestCase):
    def test_mp3_duration_and_audio_only_with_background_options(self):
        for has_audio, volume in [(True, 0), (True, 0.15), (False, 0.15)]:
            with self.subTest(has_audio=has_audio, volume=volume), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'source.mp4'
                command = ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=10:d=3']
                if has_audio:
                    command += ['-f', 'lavfi', '-i', 'sine=frequency=220:duration=3']
                engine.run(command + ['-c:v', 'libx264', str(source)])
                def speech(text, voice, rate, provider, target):
                    engine.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=600:duration=1', str(target)])
                job = dict(directory=directory, source=str(source), duration=3,
                           segments=[dict(start=1, end=2, en='Hello.', id='Halo.')],
                           **app.options({'output_mode': 'audio', 'original_volume': volume}))
                updates = []
                with patch.object(engine, 'synthesize', speech):
                    engine.render(job, lambda **values: updates.append(values), lambda: None)
                media = engine.probe(root / 'hasil.mp3')
                self.assertEqual([s['codec_type'] for s in media['streams']], ['audio'])
                self.assertAlmostEqual(float(media['format']['duration']), 3, delta=0.15)
                self.assertFalse((root / 'hasil.mp4').exists())
                self.assertEqual(updates[-1]['status'], 'done')


if __name__ == '__main__':
    unittest.main()
