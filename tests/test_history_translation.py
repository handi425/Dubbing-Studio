from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ai_settings
import app
import engine
import openrouter_translate
import supertonic_voice


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


class OpenRouterTranslationTests(unittest.TestCase):
    settings = {'openrouter_key':'sk-or-v1-dummy-test-key','openrouter_model':'example/model:free'}

    def test_options_require_key_and_accept_openrouter_for_non_indonesian(self):
        with patch.object(supertonic_voice, 'ready', return_value=True):
            with patch.object(app, 'read_user_settings', return_value=self.settings):
                options = app.options({'translator':'openrouter','language':'fr','tts':'supertonic'})
                self.assertEqual(options['translator'],'openrouter')
                self.assertNotIn('openrouter_key',options)
            with patch.object(app, 'read_user_settings', return_value={'openrouter_key':''}):
                with self.assertRaisesRegex(ValueError,'API key'):
                    app.options({'translator':'openrouter','tts':'supertonic'})

    def test_translator_calls_selected_model_and_returns_output(self):
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'Bonjour.'}}]}
        with patch.object(openrouter_translate,'read_user_settings',return_value=self.settings), \
             patch.object(openrouter_translate.requests,'post',return_value=response) as remote:
            result=engine.translate_text('Hello.','openrouter','fr')
            self.assertEqual(result,'Bonjour.')
            body=remote.call_args.kwargs['json']
            self.assertEqual(body['model'],'example/model:free')
            self.assertEqual(body['messages'][1]['content'],'Hello.')
            self.assertIn('fr',body['messages'][0]['content'])
            self.assertEqual(remote.call_args.args[0],'https://openrouter.ai/api/v1/chat/completions')

    def test_limit_error_and_truncated_translation_are_not_accepted(self):
        response=Mock(status_code=429)
        with patch.object(openrouter_translate,'read_user_settings',return_value=self.settings), \
             patch.object(openrouter_translate.requests,'post',return_value=response):
            with self.assertRaisesRegex(ValueError,'Batas pemakaian'):
                engine.translate_text('Hello.','openrouter','id')
            response.status_code=200
            response.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'Partial'}}]}
            with self.assertRaisesRegex(ValueError,'terpotong'):
                engine.translate_text('Hello.','openrouter','id')

    def test_translation_cache_is_separate_for_selected_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); subtitle=root/'source.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello.\n',encoding='utf-8')
            job=dict(directory=temporary,source=str(root/'source.mp4'),subtitle=str(subtitle),translator='openrouter',language='fr')
            config=dict(self.settings)
            with patch.object(engine.shutil,'which',return_value='ffmpeg'), \
                 patch.object(engine,'probe',return_value={'streams':[{'codec_type':'video'}]}), \
                 patch.object(engine,'media_duration',return_value=2), \
                 patch.object(ai_settings,'read_user_settings',return_value=config), \
                 patch.object(engine,'translate_text',side_effect=['Bonjour.','Salut.']) as translate:
                for _ in range(2): engine.prepare(job,lambda **kwargs: None,lambda: None)
                self.assertEqual(translate.call_count,1)
                config['openrouter_model']='example/other:free'
                engine.prepare(job,lambda **kwargs: None,lambda: None)
                self.assertEqual(translate.call_count,2)
                self.assertIn('Salut.',(root/'subtitle.fr.srt').read_text(encoding='utf-8'))
