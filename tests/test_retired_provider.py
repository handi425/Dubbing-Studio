import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import engine


class RetiredProviderTests(unittest.TestCase):
    def test_removed_endpoints_and_provider_do_not_make_network_requests(self):
        client = app.app.test_client()
        with patch.object(engine.requests, 'get') as get, patch.object(engine.requests, 'post') as post:
            for route in ('/api/settings', '/api/openrouter/models', '/api/google/settings', '/api/google/test'):
                self.assertEqual(client.get(route).status_code, 404)
            for route in ('/api/settings', '/api/google/settings', '/api/google/test', '/api/jobs/demo/grammar', '/api/jobs/demo/improve/0'):
                self.assertEqual(client.post(route, json={}, headers={'X-Dubbing-Studio':'1'}).status_code,404)
            with self.assertRaises(ValueError):
                app.options({'tts':'edge','translator':'openrouter'})
            with self.assertRaisesRegex(ValueError,'tidak tersedia'):
                engine.translate_text('Hello.','openrouter')
            with self.assertRaisesRegex(ValueError,'tidak tersedia'):
                engine.prepare({'translator':'openrouter'},lambda **v:None,lambda:None)
            for provider in ('azure', 'google_cloud'):
                with self.assertRaises(ValueError):
                    engine.translate_text('Hello.', provider)
            get.assert_not_called()
            post.assert_not_called()

    def test_saved_translations_from_retired_provider_remain_editable(self):
        with tempfile.TemporaryDirectory() as directory:
            job=dict(id='legacy',directory=directory,title='Legacy',status='review',
                     segments=[dict(start=0,end=2,en='Hello.',id='Halo.')],
                     **app.options({'tts':'edge'}))
            job['translator']='openrouter'
            with patch.object(app,'jobs',{'legacy':job}):
                result=app.app.test_client().post('/api/jobs/legacy/save',
                    json={'translations':['Selamat datang.']},headers={'X-Dubbing-Studio':'1'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(job['translator'],'openrouter')
            self.assertIn('Selamat datang.',(Path(directory)/'subtitle.id.srt').read_text(encoding='utf-8'))

    def test_updated_ui_is_not_cached(self):
        for route in ('/', '/static/app.js', '/static/style.css'):
            response=app.app.test_client().get(route)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            response.close()
