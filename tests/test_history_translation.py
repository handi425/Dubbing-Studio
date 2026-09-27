import unittest
from unittest.mock import patch

import app


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.jobs = {str(i):dict(id=str(i), title=f'Lesson {i}', status='review', source='private',
                                directory='private', segments=[{'id':'large text'}]) for i in range(23)}

    def test_pages_are_latest_first_without_private_paths_or_segments(self):
        with patch.object(app, 'jobs', self.jobs):
            first = self.client.get('/api/history?page=1&page_size=10').json
            last = self.client.get('/api/history?page=3&page_size=10').json
            self.assertEqual((first['total'],first['pages'],len(first['items'])),(23,3,10))
            self.assertEqual(first['items'][0]['id'],'22')
            self.assertEqual([item['id'] for item in last['items']],['2','1','0'])
            self.assertFalse({'source','directory','segments'} & first['items'][0].keys())

    def test_page_clamps_after_deletion_and_empty_history_is_valid(self):
        with patch.object(app, 'jobs', self.jobs):
            result = self.client.get('/api/history?page=99&page_size=20').json
            self.assertEqual((result['page'],len(result['items'])),(2,3))
        with patch.object(app, 'jobs', {}):
            result = self.client.get('/api/history?page=2').json
            self.assertEqual((result['page'],result['pages'],result['items']),(1,1,[]))

    def test_invalid_paging_is_rejected(self):
        for query in ('page=-1','page=abc','page_size=9999','page_size=0'):
            self.assertEqual(self.client.get('/api/history?'+query).status_code,400)

    def test_sort_applies_to_all_pages_and_names_use_numeric_order(self):
        with patch.object(app, 'jobs', self.jobs):
            first = self.client.get('/api/history?sort=title&direction=asc').json
            second = self.client.get('/api/history?sort=title&direction=asc&page=2').json
            self.assertEqual([j['id'] for j in first['items']], [str(i) for i in range(10)])
            self.assertEqual(second['items'][0]['id'], '10')
            descending = self.client.get('/api/history?sort=title&direction=desc').json
            self.assertEqual(descending['items'][0]['id'], '22')
            self.assertEqual(self.client.get('/api/history?sort=unknown').status_code, 400)
            self.assertEqual(self.client.get('/api/history?direction=unknown').status_code, 400)

    def test_sort_status_language_format_duration_and_stable_ties(self):
        values = {
            'a':dict(id='a',title='Same',status='done',language='id',output_mode='video',duration=100),
            'b':dict(id='b',title='Same',status='error',language='fr',output_mode='audio',duration=20),
            'c':dict(id='c',title='Same',status='review',language='id',output_mode='video')}
        with patch.object(app, 'jobs', values):
            for field, expected in [('title',['a','b','c']),('status',['b','a','c']),
                                    ('language',['a','c','b']),('format',['b','a','c']),('duration',['c','b','a'])]:
                with self.subTest(field=field):
                    result=self.client.get('/api/history?sort='+field+'&direction=asc').json
                    self.assertEqual([j['id'] for j in result['items']],expected)
