import json
import unittest
from unittest.mock import Mock, patch
import app
from grammar_ai import correct_items, correction_warning


class GrammarTests(unittest.TestCase):
    def test_guard_rejects_fact_negation_abbreviation_and_rewrite_changes(self):
        for before, after in [('Harga 100 rupiah.', 'Harga 200 rupiah.'),
                              ('Saya tidak setuju.', 'Saya setuju.'),
                              ('Gunakan API ini.', 'Gunakan SDK ini.'),
                              ('Selamat datang.', 'Silakan mulai mengikuti seluruh pelajaran.')]:
            self.assertTrue(correction_warning(before, after))
        self.assertEqual(correction_warning('Saya makan .', 'Saya makan.'), '')

    def test_structured_response_and_conservative_guard(self):
        items=[{'index':0,'text':'Saya makan .'}, {'index':1,'text':'Harga 100 rupiah.'}]
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'message':{'content':json.dumps({'items':[
            {'index':0,'text':'Saya makan.'},{'index':1,'text':'Harga 200 rupiah.'}]})}}]}
        settings={'openrouter_key':'dummy','openrouter_model':'openrouter/free'}
        with patch('grammar_ai.requests.post',return_value=response) as remote:
            result=correct_items(items,'id',settings)
        self.assertEqual(result[0]['text'],'Saya makan.')
        self.assertEqual(result[1]['text'],items[1]['text'])
        self.assertTrue(result[1]['warning'])
        self.assertIn('Do NOT paraphrase',remote.call_args.kwargs['json']['messages'][0]['content'])

    def test_invalid_response_rejected(self):
        settings={'openrouter_key':'dummy','openrouter_model':'openrouter/free'}
        for content in ['invalid', '{"items":[]}', '{"items":[{"index":2,"text":"Halo."}]}']:
            response=Mock(status_code=200)
            response.json.return_value={'choices':[{'message':{'content':content}}]}
            with patch('grammar_ai.requests.post',return_value=response), self.assertRaises(ValueError):
                correct_items([{'index':0,'text':'Halo.'}],'id',settings)

    def test_endpoint_uses_unsaved_text_without_mutation_and_validates_indexes(self):
        job={'status':'review','language':'id','segments':[{'id':'Asli.'}]}
        items=[{'index':0,'text':'Edit terbaru .'}]
        with patch.object(app,'find_job',return_value=job), patch.object(app,'read_user_settings',return_value={}), patch('grammar_ai.correct_items',return_value=items) as correct:
            client=app.app.test_client()
            response=client.post('/api/jobs/demo/grammar',json={'items':items},headers={'X-Dubbing-Studio':'1'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(correct.call_args.args[0],items)
            self.assertEqual(job['segments'][0]['id'],'Asli.')
            for invalid in [[], items*2, [{'index':3,'text':'Invalid'}]]:
                self.assertEqual(client.post('/api/jobs/demo/grammar',json={'items':invalid},headers={'X-Dubbing-Studio':'1'}).status_code,400)
