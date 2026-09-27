import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import engine
import google_translate


class MultilingualTests(unittest.TestCase):
    def test_auto_detection_reaches_translation_with_original_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = Mock()
            factory.return_value.transcribe.return_value = (
                iter([types.SimpleNamespace(start=0, end=2, text='Bonjour.')]),
                types.SimpleNamespace(language='fr'))
            job = dict(directory=directory, source='video.mp4', model='base.en', translator='google', language='id')
            def translate(segments, target, cache, save, check, progress, source):
                self.assertEqual(source, 'fr')
                self.assertEqual(segments[0]['en'], 'Bonjour.')
                segments[0]['id'] = 'Halo.'
            updates = []
            with patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=factory)}), \
                    patch.object(engine.shutil, 'which', return_value='ffmpeg'), \
                    patch.object(engine, 'probe', return_value={'streams':[{'codec_type':'video'}]}), \
                    patch.object(engine, 'media_duration', return_value=3), \
                    patch.object(engine, 'run'), patch.object(google_translate, 'translate_segments', side_effect=translate):
                engine.prepare(job, lambda **v: updates.append(v), lambda: None)
                engine.prepare(job, lambda **v: updates.append(v), lambda: None)
                self.assertEqual(factory.call_count, 1)
            self.assertEqual(factory.call_args.args[0], 'base')
            self.assertIsNone(factory.return_value.transcribe.call_args.kwargs['language'])
            self.assertEqual(job['source_language'], 'fr')
            self.assertEqual(updates[-1]['status'], 'review')
            self.assertIn('Bonjour.', (Path(directory)/'subtitle.source.srt').read_text())
            self.assertIn('Halo.', (Path(directory)/'subtitle.id.srt').read_text())

    def test_cache_is_separate_for_different_source_languages(self):
        self.assertNotEqual(google_translate.cache_key('chat','id','fr'), google_translate.cache_key('chat','id','en'))
        client = Mock()
        client.get.return_value = Mock(status_code=200, json=lambda: [[['Halo.']]])
        google_translate._request(client,'Bonjour.','id',lambda:None,lambda msg:None,source='fr')
        self.assertEqual(client.get.call_args.kwargs['params']['sl'],'fr')

    def test_english_output_does_not_overwrite_source_track(self):
        with tempfile.TemporaryDirectory() as directory:
            engine.write_subtitles([dict(start=0,end=2,en='Bonjour.',id='Hello.')],Path(directory),'en')
            self.assertIn('Bonjour.', (Path(directory)/'subtitle.source.srt').read_text())
            self.assertIn('Hello.', (Path(directory)/'subtitle.en.srt').read_text())

    def test_local_non_english_is_explicit_and_same_language_skips_translation(self):
        with self.assertRaisesRegex(ValueError,'hanya mendukung sumber Inggris'):
            engine.translate_text('Bonjour.','local',source='fr')
        self.assertEqual(engine.translate_text('Halo.','google',source='id'), 'Halo.')
        self.assertEqual(app.options({'tts':'edge'})['model'],'base')
        self.assertEqual(app.options({'tts':'edge','model':'small.en'})['model'],'small')
