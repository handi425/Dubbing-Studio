import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import app
import engine


class SubtitleTests(unittest.TestCase):
    def test_vtt_settings_html_and_broken_sentence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.vtt'
            path.write_text('WEBVTT\n\nNOTE Ignore this\n\n00:01.200 --> 00:02.500 align:start\n<v Speaker>Hello &amp; welcome\n\n00:02.500 --> 00:04.000\nto this course.\n', encoding='utf-8')
            segments = engine.group_segments(engine.read_subtitles(path))
            self.assertEqual(len(segments), 1)
            self.assertEqual(segments[0]['en'], 'Hello & welcome to this course.')
            self.assertEqual(segments[0]['start'], 1.2)
            self.assertEqual(segments[0]['end'], 4)

    def test_srt_round_trip_hour_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            segments = [{'start':3599.9996,'end':3601.25,'en':'Test.','id':'Uji.'}]
            engine.write_subtitles(segments, Path(directory))
            parsed = engine.read_subtitles(Path(directory) / 'subtitle.id.srt')
            self.assertEqual(parsed[0]['start'], 3600)
            self.assertEqual(parsed[0]['en'], 'Uji.')

    def test_matching_course_subtitle(self):
        path = app.LIBRARY / '2. Fundamentals' / 'CHP 1 1. Introduction to Harmonic Trading.mp4'
        if path.exists():
            self.assertEqual(app.associated_subtitle(path).name, '1. Introduction to Harmonic Trading.vtt')

    def test_invalid_ranges(self):
        for data in [{'rate':100}, {'original_volume':'nan'}, {'voice':'unknown'}]:
            with self.assertRaises(ValueError):
                app.options(data)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_external_origin_and_host_rejected(self):
        self.assertEqual(self.client.post('/api/jobs', headers={'Origin':'https://other.test','X-Dubbing-Studio':'1'}).status_code, 403)
        self.assertEqual(self.client.get('/api/info', headers={'Host':'other.test'}).status_code, 403)

    def test_traversal_and_invalid_upload_rejected(self):
        headers = {'X-Dubbing-Studio':'1'}
        self.assertEqual(self.client.post('/api/jobs', data={'library_path':'../../Windows/win.ini'}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post('/api/jobs', data={'video':(io.BytesIO(b'x'),'bad.exe')}, headers=headers).status_code, 400)

    def test_edit_validation_and_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            job = dict(id='test-edit', directory=directory, title='test', status='review',
                       segments=[dict(start=0,end=2,en='Hello.',id='Halo.')], **app.options({'tts': 'edge'}))
            app.jobs[job['id']] = job
            try:
                headers = {'X-Dubbing-Studio':'1'}
                self.assertEqual(self.client.post('/api/jobs/test-edit/save', json={'translations':['']}, headers=headers).status_code, 400)
                response = self.client.post('/api/jobs/test-edit/save', json={'translations':['Selamat datang.']}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertIn('Selamat datang.', (Path(directory)/'subtitle.id.srt').read_text(encoding='utf-8'))
                job['status'] = 'rendering'
                self.assertEqual(self.client.post('/api/jobs/test-edit/save', json={'translations':['X']}, headers=headers).status_code, 409)
            finally:
                del app.jobs[job['id']]


class MediaTests(unittest.TestCase):
    def test_render_duration_tracks_and_initial_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.mp4'
            engine.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=10:d=5',
                        '-f','lavfi','-i','sine=frequency=220:duration=5','-c:v','libx264','-c:a','aac',str(source)])
            def fake_speech(text, voice, rate, provider, target):
                engine.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=600:duration=2',str(target)])
            job = dict(directory=directory, source=str(source), duration=5,
                       segments=[dict(start=1,end=2,en='Hello.',id='Halo.'),dict(start=3,end=4,en='Welcome.',id='Selamat datang.')], **app.options({'tts': 'edge'}))
            updates = []
            with patch.object(engine, 'synthesize', fake_speech):
                engine.render(job, lambda **values: updates.append(values), lambda: None)
            result = root/'hasil.mp4'
            media = engine.probe(result)
            self.assertAlmostEqual(float(media['format']['duration']),5,delta=.15)
            self.assertEqual(len([s for s in media['streams'] if s['codec_type']=='audio']),2)
            self.assertTrue(any(s['codec_type']=='subtitle' for s in media['streams']))
            self.assertEqual(updates[-1]['status'],'done')
            pcm = engine.run(['ffmpeg','-v','error','-i',str(result),'-map','0:a:0','-t','0.8','-f','s16le','-ac','1','pipe:1'])
            import array
            samples = array.array('h',pcm)
            self.assertLess(max(abs(s) for s in samples),10)


if __name__ == '__main__':
    unittest.main()
