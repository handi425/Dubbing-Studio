import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import app


class OpenRouterSettingsTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.headers = {'X-Dubbing-Studio': '1'}

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI storage')
    def test_key_encrypted_at_rest_masked_in_api_and_retained_on_blank_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'settings.json'
            with patch.object(app, 'user_settings_path', return_value=target):
                secret = 'sk-or-v1-test-placeholder-not-a-real-key'
                response = self.client.post('/api/settings', headers=self.headers,
                    json={'openrouter_key': secret, 'openrouter_model': 'openrouter/free'})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(secret, response.get_data(as_text=True))
                self.assertNotIn(secret, target.read_text(encoding='utf-8'))
                self.assertEqual(app.read_user_settings()['openrouter_key'], secret)
                visible = self.client.get('/api/settings').json
                self.assertTrue(visible['openrouter_configured'])
                self.assertNotIn('openrouter_key', visible)
                response = self.client.post('/api/settings', headers=self.headers,
                    json={'openrouter_key':'', 'openrouter_model':'openrouter/free'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(app.read_user_settings()['openrouter_key'], secret)

    def test_improvement_returns_text_without_changing_saved_project(self):
        job = {'status':'review', 'language':'id', 'segments':[{'id':'Selamat datang.'}]}
        response = Mock(status_code=200)
        response.json.return_value = {'choices':[{'message':{'content':json.dumps({'items':[{'index':0,'text':'Selamat datang.'}]})}}]}
        with patch.object(app, 'find_job', return_value=job), \
             patch.object(app, 'read_user_settings', return_value={
                 'openrouter_key':'sk-or-v1-placeholder', 'openrouter_model':'openrouter/free'}), \
             patch.object(app.requests, 'post', return_value=response) as remote:
            result = self.client.post('/api/jobs/demo/improve/0', json={}, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['text'], 'Selamat datang.')
            self.assertEqual(job['segments'][0]['id'], 'Selamat datang.')
            self.assertEqual(remote.call_args.kwargs['json']['model'], 'openrouter/free')

    def test_ui_assets_require_fresh_copy_after_an_update(self):
        for route in ('/', '/static/app.js', '/static/style.css'):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            response.close()
