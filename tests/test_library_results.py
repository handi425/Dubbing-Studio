import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class LibraryResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / 'course'
        self.library.mkdir()
        self.data = self.root / 'data'
        self.data.mkdir()
        for name in ['one', 'two']:
            (self.library / name).mkdir()
            (self.library / name / 'lesson.mp4').write_bytes(b'0123456789')
        for key, value in [('DATA', self.data), ('LIBRARY', self.library), ('jobs', {})]:
            context = patch.object(app, key, value)
            context.start()
            self.addCleanup(context.stop)
        self.client = app.app.test_client()

    def job(self, job_id, relative='one/lesson.mp4', mode='video', status='done', stamp=100):
        directory = self.data / job_id
        directory.mkdir()
        output = directory / ('hasil.mp3' if mode == 'audio' else 'hasil.mp4')
        output.write_bytes(b'output')
        os.utime(output, (stamp, stamp))
        job = dict(id=job_id, title='lesson', source=str(self.library / relative), directory=str(directory), status=status)
        if mode == 'audio':
            job['output_mode'] = mode
        app.jobs[job_id] = job
        return output

    def test_old_jobs_match_exact_source_and_latest_result_per_format(self):
        self.job('old')  # Older jobs lack playlist_id and output_mode.
        self.job('new', stamp=200)
        self.job('audio', mode='audio', stamp=150)
        self.job('other-chapter', relative='two/lesson.mp4')
        result = self.client.get('/api/playlists/default/results').json
        self.assertEqual({r['job_id'] for r in result['one/lesson.mp4']}, {'new', 'audio'})
        self.assertEqual(result['two/lesson.mp4'][0]['job_id'], 'other-chapter')
        self.assertNotIn('source', result['one/lesson.mp4'][0])
        self.assertEqual(self.client.get('/api/playlists/default').json['results'], result)

    def test_unfinished_missing_empty_outputs_and_other_courses_not_marked(self):
        self.job('rendering', status='rendering')
        self.job('review', status='review')
        self.job('missing').unlink()
        self.job('empty').write_bytes(b'')
        self.job('outside', relative='../elsewhere/lesson.mp4')
        self.assertEqual(self.client.get('/api/playlists/default/results').json, {})

    def test_result_updates_when_done_or_edited_and_downloads_are_scoped(self):
        self.job('audio', mode='audio', status='rendering')
        self.assertFalse(self.client.get('/api/playlists/default/results').json)
        app.jobs['audio']['status'] = 'done'
        result = self.client.get('/api/playlists/default/results').json['one/lesson.mp4'][0]
        response = self.client.get(result['download_url'])
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        response.close()
        app.jobs['audio']['status'] = 'review'
        self.assertFalse(self.client.get('/api/playlists/default/results').json)
        self.assertEqual(self.client.get(result['media_url']).status_code, 409)

    def test_original_video_stream_supports_seek_ranges_and_missing_source(self):
        self.job('audio', mode='audio')
        response = self.client.get('/api/jobs/audio/source', headers={'Range': 'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b'2345')
        self.assertEqual(response.mimetype, 'video/mp4')
        self.assertEqual(response.headers['Content-Range'], 'bytes 2-5/10')
        response.close()
        (self.library / 'one/lesson.mp4').unlink()
        self.assertEqual(self.client.get('/api/jobs/audio/source').status_code, 404)
        result = self.client.get('/api/playlists/default/results').json['one/lesson.mp4'][0]
        self.assertFalse(result['source_available'])
        self.assertEqual(result['mode'], 'audio')  # MP3 remains downloadable.

    def test_source_route_requires_completed_audio_job(self):
        self.job('video')
        self.job('pending', mode='audio', status='rendering')
        self.assertEqual(self.client.get('/api/jobs/video/source').status_code, 409)
        self.assertEqual(self.client.get('/api/jobs/pending/source').status_code, 409)
        self.assertEqual(self.client.get('/api/jobs/unknown/source').status_code, 404)


if __name__ == '__main__':
    unittest.main()
