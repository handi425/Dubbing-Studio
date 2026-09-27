import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import engine
import google_translate


class MultilingualTests(unittest.TestCase):
    def test_same_language_subtitle_bypasses_all_translators_and_model_download(self):
        for provider in ('google', 'local'):
            for selection, target, text in [('same', 'id', 'Selamat datang di kursus ini.'),
                                             ('id', 'id', 'Mari kita mulai belajar.'),
                                             ('same', 'fr', 'Bonjour.')]:
                with self.subTest(provider=provider, selection=selection, target=target), tempfile.TemporaryDirectory() as directory:
                    subtitle = Path(directory) / 'input.srt'
                    subtitle.write_text(f'1\n00:00:01,000 --> 00:00:02,500\n{text}\n', encoding='utf-8')
                    job = dict(directory=directory, source='video.mp4', subtitle=str(subtitle),
                               translator=provider, language=target, subtitle_language=selection)
                    updates = []
                    with patch.object(engine.shutil, 'which', return_value='ffmpeg'), \
                            patch.object(engine, 'probe', return_value={'streams':[{'codec_type':'video'}]}), \
                            patch.object(engine, 'media_duration', return_value=3), \
                            patch.object(google_translate, 'translate_segments') as google, \
                            patch.object(engine, 'translate_text') as translate, \
                            patch('local_translate.ensure_model') as download:
                        # Both the first run and resume must preserve the supplied text.
                        engine.prepare(job, lambda **v: updates.append(v), lambda: None)
                        engine.prepare(job, lambda **v: updates.append(v), lambda: None)
                        google.assert_not_called()
                        translate.assert_not_called()
                        download.assert_not_called()
                    self.assertEqual(job['source_language'], target)
                    self.assertEqual(updates[-1]['segments'], [dict(start=1, end=2.5, en=text, id=text)])
                    self.assertIn('tanpa terjemahan', updates[-1]['message'])
                    self.assertIn(text, (Path(directory) / f'subtitle.{target}.srt').read_text(encoding='utf-8'))

    def test_subtitle_language_options(self):
        self.assertEqual(app.options({'tts':'edge', 'subtitle_language':'same'})['subtitle_language'], 'same')
        with self.assertRaisesRegex(ValueError, 'Bahasa subtitle'):
            app.options({'tts':'edge', 'subtitle_language':'invalid'})

    def test_direct_mode_never_falls_back_to_whisper_without_subtitles(self):
        with patch.object(engine, 'probe') as probe:
            with self.assertRaisesRegex(ValueError, 'memerlukan subtitle'):
                engine.prepare({'subtitle_language':'same'}, lambda **v: None, lambda: None)
            probe.assert_not_called()

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
