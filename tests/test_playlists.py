import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'application' / 'data'
        self.data.mkdir(parents=True)
        self.default = self.root / 'default-course'
        self.default.mkdir()
        for key, value in [('DATA', self.data), ('LIBRARY', self.default), ('BASE', self.data.parent), ('jobs', {})]:
            patcher = patch.object(app, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.app.test_client()
        self.headers = {'X-Dubbing-Studio': '1'}

    def post(self, path, **kwargs):
        return self.client.post('/api/' + path, headers=self.headers, **kwargs)

    def course_folder(self):
        root = self.root / 'Course with spaces'
        (root / '2. Chapter' / 'Nested').mkdir(parents=True)
        for name in ['10. Lesson.MP4', '2. Lesson.mp4']:
            (root / '2. Chapter' / name).write_bytes(b'video')
        (root / '2. Chapter' / '2. Lesson.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nHello.')
        (root / '2. Chapter' / 'Nested' / 'Video.webm').write_bytes(b'video')
        (root / 'notes.pdf').write_bytes(b'not video')
        return root

    def test_local_recursive_index_persistence_duplicate_and_refresh(self):
        root = self.course_folder()
        response = self.post('playlists', json={'folder': str(root)})
        self.assertEqual(response.status_code, 201)
        course = response.json
        self.assertEqual(course['name'], root.name)
        self.assertEqual(course['count'], 3)
        self.assertEqual([v['name'] for v in course['videos']], ['2. Lesson', '10. Lesson', 'Video'])
        self.assertTrue(course['videos'][0]['subtitle'])
        self.assertEqual(course['videos'][2]['folder'], '2. Chapter/Nested')
        # Fresh store and client use the on-disk index, without any process cache.
        self.assertEqual(app.courses().detail(course['id'])['videos'], course['videos'])
        self.assertTrue((self.data / 'playlists' / course['id'] / 'playlist.json').exists())
        duplicate = self.post('playlists', json={'folder': str(root)})
        self.assertEqual(duplicate.json['id'], course['id'])
        self.assertEqual(len(self.client.get('/api/playlists').json), 2)
        (root / 'new.mov').write_bytes(b'video')
        self.assertEqual(self.post(f"playlists/{course['id']}/refresh", json={}).json['count'], 4)

    def test_folder_upload_preserves_nested_paths_and_subtitles(self):
        course = self.post('playlists', json={'kind': 'upload', 'name': 'My Course', 'source_folder': 'Original'}).json
        course_id = course['id']
        self.assertEqual(course['status'], 'importing')
        for name in ['Chapter 1/1. Lesson.mp4', 'Chapter 2/1. Lesson.mp4', 'Chapter 1/1. Lesson.srt']:
            response = self.post(f'playlists/{course_id}/files', data={'path': name, 'file': (io.BytesIO(b'test'), Path(name).name)})
            self.assertEqual(response.status_code, 200)
        # Re-uploading the same path resumes safely without duplicating a lesson.
        self.post(f'playlists/{course_id}/files', data={'path': 'Chapter 1/1. Lesson.mp4', 'file': (io.BytesIO(b'updated'), 'video.mp4')})
        response = self.post(f'playlists/{course_id}/finish', json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['count'], 2)
        self.assertEqual(response.json['status'], 'ready')
        self.assertTrue(response.json['videos'][0]['subtitle'])
        source, subtitle = app.courses().resolve(course_id, 'Chapter 1/1. Lesson.mp4')
        self.assertEqual(source.read_bytes(), b'updated')
        self.assertEqual(subtitle.suffix, '.srt')
        self.assertEqual(self.client.get(f'/api/playlists/{course_id}').json['source_folder'], 'Original')
        self.assertEqual(self.post(f'playlists/{course_id}/files', data={'path': 'x.mp4', 'file': (io.BytesIO(b'x'), 'x.mp4')}).status_code, 400)

    def test_registered_course_can_create_audio_batch_with_correct_sources(self):
        root = self.course_folder()
        course = self.post('playlists', json={'folder': str(root)}).json
        with patch.object(app.executor, 'submit') as submit:
            response = self.post('jobs/batch', data={'playlist_id': course['id'], 'library_path': [v['path'] for v in course['videos']], 'output_mode': 'audio'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(submit.call_count, 3)
        for job in app.jobs.values():
            self.assertEqual(job['playlist_id'], course['id'])
            self.assertTrue(Path(job['source']).is_relative_to(root))
            self.assertEqual(job['output_mode'], 'audio')

    def test_missing_drive_and_missing_video_report_clear_error(self):
        root = self.course_folder()
        course = self.post('playlists', json={'folder': str(root)}).json
        root.rename(root.with_name('moved-course'))
        detail = self.client.get(f"/api/playlists/{course['id']}").json
        self.assertFalse(detail['available'])
        self.assertEqual(detail['count'], 3)
        self.assertEqual(self.post(f"playlists/{course['id']}/refresh", json={}).status_code, 400)
        self.assertEqual(self.post('jobs', data={'playlist_id': course['id'], 'library_path': course['videos'][0]['path']}).status_code, 400)

    def test_invalid_paths_and_non_media_cannot_escape_course(self):
        course = self.post('playlists', json={'kind': 'upload', 'name': 'Test'}).json
        for path in ['../outside.mp4', '/outside.mp4', 'C:/outside.mp4', 'part/../../outside.mp4', 'file.exe', 'file.mp4:stream']:
            with self.subTest(path=path):
                response = self.post(f"playlists/{course['id']}/files", data={'path': path, 'file': (io.BytesIO(b'x'), 'x.mp4')})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post(f"playlists/{course['id']}/finish", json={}).status_code, 400)
        self.assertEqual(self.post('playlists', json={'folder': str(self.data)}).status_code, 400)
        self.assertEqual(self.post('playlists', json={'folder': str(self.root / 'missing')}).status_code, 400)
        self.assertEqual(self.post('jobs', data={'playlist_id': course['id'], 'library_path': 'x.mp4'}).status_code, 400)

    def test_default_library_preserved_as_course(self):
        (self.default / 'old.mp4').write_bytes(b'video')
        listing = self.client.get('/api/playlists').json
        self.assertEqual(listing[0]['id'], 'default')
        self.assertEqual(listing[0]['count'], 1)
        self.assertEqual(self.post('playlists', json={'folder': str(self.default)}).json['id'], 'default')
        with patch.object(app.executor, 'submit'):
            response = self.post('jobs', data={'library_path': 'old.mp4'})
        self.assertEqual(response.status_code, 201)


if __name__ == '__main__':
    unittest.main()
