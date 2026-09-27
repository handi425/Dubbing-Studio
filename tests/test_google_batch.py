import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

import engine
import google_translate as google


def response(text='', status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = [[[text, None]]]
    return result


def echo_response(url, params, **kwargs):
    text = params['q'].replace('First sentence.', 'Kalimat pertama.').replace('Second sentence.', 'Kalimat kedua.').replace('Long input sentence.', 'Kalimat masukan panjang.').replace('A long sentence with unicode', 'Kalimat panjang dengan unicode')
    return response(text)


class GoogleBatchTests(unittest.TestCase):
    def setUp(self):
        self.segments = [dict(start=0.5, end=2, en='First sentence.', id=''),
                         dict(start=3, end=5, en='Second sentence.', id='')]
        self.cache = {}
        self.save = Mock()
        self.progress = Mock()
        self.client = Mock()
        self.client.get.side_effect = echo_response
        self.session = patch.object(google.requests, 'Session')
        self.session.start().return_value.__enter__.return_value = self.client
        self.addCleanup(self.session.stop)
        self.wait = patch.object(google, '_wait').start()
        self.addCleanup(patch.stopall)

    def run_batch(self, check=lambda: None):
        google.translate_segments(self.segments, 'id', self.cache, self.save, check, self.progress)

    def test_two_segments_use_one_request_and_keep_their_timestamps(self):
        before = [(s['start'], s['end'], s['en']) for s in self.segments]
        self.run_batch()
        self.assertEqual(self.client.get.call_count, 1)

        self.assertEqual([s['id'] for s in self.segments], ['Kalimat pertama.', 'Kalimat kedua.'])
        self.assertEqual([(s['start'], s['end'], s['en']) for s in self.segments], before)
        self.save.assert_called_once()
        self.run_batch()
        self.assertEqual(self.client.get.call_count, 1)

    def test_only_empty_part_is_retried_without_batch_markers(self):
        def missing_one(url, params, **kwargs):
            payload=params['q']
            if '[[' in payload:
                return response(payload.replace('First sentence.', 'Kalimat pertama.').replace('Second sentence.', ''))
            self.assertEqual(payload, 'Second sentence.')
            return response('Kalimat kedua.')
        self.client.get.side_effect=missing_one
        self.run_batch()
        self.assertEqual(self.client.get.call_count, 2)
        self.assertEqual([s['id'] for s in self.segments], ['Kalimat pertama.','Kalimat kedua.'])
        self.assertTrue(all(s['start'] < s['end'] for s in self.segments))

    def test_unchanged_old_cache_is_rechecked_but_short_terms_are_preserved(self):
        original='Welcome to the next lesson.'
        self.segments=[dict(start=0,end=2,en=original,id=''),dict(start=3,end=4,en='Forex',id='')]
        self.cache[google.cache_key(original,'id')]=original
        self.cache[google.cache_key('Forex','id')]='Forex'
        def answer(url,params,**kwargs):
            if '[[' in params['q']:
                return response(params['q'])
            self.assertEqual(params['q'],original)
            return response('Selamat datang di pelajaran berikutnya.')
        self.client.get.side_effect=answer
        self.run_batch()
        self.assertEqual(self.client.get.call_count,2)
        self.assertEqual(self.segments[0]['id'],'Selamat datang di pelajaran berikutnya.')
        self.assertEqual(self.segments[1]['id'],'Forex')

    def test_persistently_unchanged_sentence_stops_instead_of_claiming_success(self):
        self.segments=[dict(start=0,end=2,en='Welcome to the next lesson.',id='')]
        self.client.get.side_effect=lambda url,params,**kw:response(params['q'])
        with self.assertRaisesRegex(ValueError,'belum terkonfirmasi'):
            self.run_batch()
        self.assertEqual(self.client.get.call_count,4)
        self.assertEqual(self.segments[0]['id'],'')

    def test_recovered_part_survives_failure_and_resume(self):
        def initial(url,params,**kw):
            if '[[' in params['q']:
                return response(params['q'].replace('First sentence.', 'Kalimat pertama.').replace('Second sentence.', ''))
            return response(status=403)
        self.client.get.side_effect=initial
        with self.assertRaises(ValueError):
            self.run_batch()
        self.assertEqual(self.cache[google.cache_key('First sentence.','id')],'Kalimat pertama.')
        self.client.get.reset_mock();self.client.get.side_effect=echo_response
        self.run_batch()
        for call in self.client.get.call_args_list:
            self.assertNotIn('First sentence.',call.kwargs['params']['q'])

    def test_old_cache_and_repeated_source_do_not_resend(self):
        self.cache[google.cache_key('First sentence.', 'id')] = 'Terjemahan lama.'
        self.segments.append(dict(start=6,end=8,en='Second sentence.',id=''))
        self.run_batch()
        payload = self.client.get.call_args.kwargs['params']['q']
        self.assertNotIn('First sentence.', payload)
        self.assertEqual(payload.count('Second sentence.'), 1)
        self.assertEqual(self.segments[0]['id'], 'Terjemahan lama.')
        self.assertEqual(self.segments[2]['id'], 'Kalimat kedua.')

    def test_changed_or_missing_markers_never_apply_translation(self):
        payload, ids = google._payload([('a',0,'First.'),('b',0,'Second.')])
        invalid = [payload.replace(f'[[{ids[-1]}]]',''),
                   payload + 'unexpected trailing text',
                   payload.replace(ids[1], ids[0]),
                   payload.replace(ids[0], 'SWAP').replace(ids[1],ids[0]).replace('SWAP',ids[1]),
                   'No markers at all', payload.replace('First.', '')]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                google._parse(value, ids)
        self.client.get.return_value = response('Translation without markers')
        self.client.get.side_effect = [response('Translation without markers'), response(status=403)]
        with self.assertRaises(ValueError):
            self.run_batch()
        self.assertEqual(self.cache, {})
        self.assertTrue(all(s['id'] == '' for s in self.segments))
        self.assertEqual(self.cache, {})

    def test_spaces_inside_markers_and_multiline_translations(self):
        payload, ids = google._payload([('a',0,'Line one.\nLine two.'),('b',0,'Another.')])
        value = payload.replace('[[','[ [ ').replace(']]',' ] ]')
        self.assertEqual(google._parse(value,ids), ['Line one.\nLine two.','Another.'])

    def test_long_unicode_cue_splits_and_restores_single_timed_segment(self):
        text = 'A long sentence with unicode 漢字 and numbers 1.5%. ' * 150
        self.segments = [dict(start=2,end=60,en=text,id='')]
        self.run_batch()
        self.assertGreater(self.client.get.call_count, 1)
        for call in self.client.get.call_args_list:
            payload = call.kwargs['params']['q']
            self.assertLessEqual(len(payload), google.MAX_CHARS)
            self.assertLessEqual(len(quote(payload,safe='')), google.MAX_ENCODED)
        self.assertEqual(len(self.segments), 1)
        self.assertEqual((self.segments[0]['start'],self.segments[0]['end']), (2,60))
        self.assertEqual(self.segments[0]['id'], text.replace('A long sentence with unicode', 'Kalimat panjang dengan unicode').strip())

    def test_partial_group_cache_resumes_after_failure_without_resending(self):
        self.segments = [dict(start=0,end=30,en='Long input sentence. ' * 400,id='')]
        payloads = []
        def fail_second(url, params, **kwargs):
            payloads.append(params['q'])
            return echo_response(url,params) if len(payloads) == 1 else response(status=403)
        self.client.get.side_effect = fail_second
        with self.assertRaisesRegex(ValueError, '403'):
            self.run_batch()
        self.assertEqual(self.segments[0]['id'], '')
        self.assertTrue(any(k.startswith('google-batch-v1:') for k in self.cache))
        # Simulate reloading the persisted cache after application restart.
        self.cache = json.loads(json.dumps(self.cache))
        self.client.get.reset_mock()
        self.client.get.side_effect = echo_response
        self.run_batch()
        self.assertTrue(self.segments[0]['id'])
        resent = [c.kwargs['params']['q'] for c in self.client.get.call_args_list]
        self.assertNotIn(payloads[0], resent)

    def test_rate_limit_honors_retry_after_and_does_not_fan_out(self):
        self.client.get.side_effect = [response(status=429,headers={'Retry-After':'45'}),
                                      response(status=429), response(status=429)]
        with self.assertRaisesRegex(ValueError, '429'):
            self.run_batch()
        self.assertEqual(self.client.get.call_count,3)
        self.assertEqual([c.args[0] for c in self.wait.call_args_list], [60,120])
        self.assertEqual(len({c.kwargs['params']['q'] for c in self.client.get.call_args_list}),1)
        self.assertEqual(self.cache,{})

    def test_cancel_during_retry_stops_immediately(self):
        self.client.get.side_effect = [response(status=429)]
        self.wait.side_effect = engine.Cancelled()
        with self.assertRaises(engine.Cancelled):
            self.run_batch()
        self.assertEqual(self.client.get.call_count,1)
        self.assertEqual(self.cache,{})

    def test_invalid_response_and_long_cooldown_fail_without_cache(self):
        for reply in (response(status=429,headers={'Retry-After':'3600'}), response(status=400)):
            self.client.get.side_effect = None
            self.client.get.return_value = reply
            with self.assertRaises(ValueError):
                self.run_batch()
        invalid = response()
        invalid.json.return_value = {'unexpected':'format'}
        self.client.get.return_value = invalid
        with self.assertRaisesRegex(ValueError, 'Format respons'):
            self.run_batch()
        self.assertEqual(self.cache,{})

    def test_prepare_collects_full_transcript_before_request_and_writes_aligned_subtitles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subtitle = root/'input.srt'
            subtitle.write_text('1\n00:00:00,500 --> 00:00:02,000\nFirst sentence.\n\n'
                                '2\n00:00:03,000 --> 00:00:05,000\nSecond sentence.\n',encoding='utf-8')
            job = dict(directory=directory,source='video.mp4',subtitle=str(subtitle),translator='google',language='id')
            def verify_source(url,params,**kwargs):
                source = json.loads((root/'transkrip.en.json').read_text(encoding='utf-8'))
                self.assertEqual(len(source),2)
                return echo_response(url,params)
            self.client.get.side_effect = verify_source
            updates=[]
            with patch.object(engine.shutil,'which',return_value='ffmpeg'), \
                 patch.object(engine,'probe',return_value={'streams':[{'codec_type':'video'}]}), \
                 patch.object(engine,'media_duration',return_value=6):
                engine.prepare(job,lambda **v:updates.append(v),lambda:None)
                self.assertEqual(updates[-1]['status'],'review')
                parsed=engine.read_subtitles(root/'subtitle.id.srt')
                self.assertEqual([s['en'] for s in parsed],['Kalimat pertama.','Kalimat kedua.'])
                self.assertEqual([(s['start'],s['end']) for s in parsed],[(0.5,2),(3,5)])
                engine.prepare(job,lambda **v:None,lambda:None)
            self.assertEqual(self.client.get.call_count,1)


if __name__ == '__main__':
    unittest.main()
