import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import engine
import local_voice
import supertonic_voice


class LocalVoiceTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(supertonic_voice, 'ready', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_offline_when_ready_and_unavailable_choice_fails(self):
        with patch.object(local_voice, 'ready', return_value=True):
            self.assertEqual(app.options({})['tts'], 'onnx')
            self.assertEqual(app.options({'tts': 'edge'})['tts'], 'edge')
            self.assertTrue(app.app.test_client().get('/api/info').json['onnx'])
        with patch.object(local_voice, 'ready', return_value=False):
            self.assertEqual(app.options({})['tts'], 'edge')
            with self.assertRaisesRegex(ValueError, 'belum tersedia'):
                app.options({'tts': 'onnx'})

    def test_source_and_bundle_model_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / 'bundle/models/voice-onnx'
            bundled.mkdir(parents=True)
            for name in ('voice.onnx', 'voice.json'):
                (bundled / name).write_text('test')
            with patch.object(local_voice, 'DATA', root / 'data'), patch.object(local_voice, 'RESOURCES', root / 'bundle'):
                self.assertEqual(local_voice.model_directory(), bundled)
                external = root / 'data/models/voice-onnx'
                external.mkdir(parents=True)
                (external / 'voice.json').write_text('incomplete')
                self.assertEqual(local_voice.model_directory(), bundled)
                (external / 'voice.onnx').write_text('complete')
                self.assertEqual(local_voice.model_directory(), external)

    def test_indonesian_numbers_and_long_tokens(self):
        text = local_voice.normalize_text('Harga 1.250,50 naik 12,5% & turun -0,25.')
        self.assertIn('seribu dua ratus lima puluh koma lima nol', text)
        self.assertIn('dua belas koma lima persen', text)
        self.assertIn('dan turun min nol koma dua lima', ' '.join(text.split()))
        self.assertTrue(all(len(word) <= 25 for word in local_voice.normalize_text('e' * 70).split()))

    def test_chunks_bound_long_editor_input_without_losing_words(self):
        text = 'Ini contoh kalimat Indonesia yang panjang. ' * 120
        chunks = list(local_voice.split_text(text))
        self.assertTrue(all(len(chunk) <= 180 for chunk in chunks))
        self.assertEqual(' '.join(chunks), text.strip())

    def test_cache_reuse_duplicate_text_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            job = dict(directory=directory, voice='id-ID-ArdiNeural', rate=0, tts='onnx',
                       segments=[{'id': 'Halo.'}, {'id': 'Halo.'}])
            target = Path(directory) / 'speech' / (local_voice.cache_key('Halo.', job) + '.wav')
            def fake_run(command, report, timeout):
                data = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
                self.assertEqual(len(data['items']), 1)
                report()
                target.write_bytes(b'completed audio')
            with patch.object(local_voice, 'ready', return_value=True), patch.object(engine, 'run', side_effect=fake_run) as run:
                local_voice.generate(job, lambda **kwargs: None, lambda: None)
                local_voice.generate(job, lambda **kwargs: None, lambda: None)
                self.assertEqual(run.call_count, 1)
                with self.assertRaises(engine.Cancelled):
                    local_voice.generate(job, lambda **kwargs: None, lambda: (_ for _ in ()).throw(engine.Cancelled()))
            self.assertNotEqual(local_voice.cache_key('Halo.', job), local_voice.cache_key('Halo.', {**job, 'rate': 30}))
            self.assertNotEqual(local_voice.cache_key('Halo.', job), local_voice.cache_key('Halo.', {**job, 'voice': 'id-ID-GadisNeural'}))

    def test_blank_tokenizer_and_empty_phonemes(self):
        config = {'vocab': ['_', 'a', 'b', ' '], 'add_blank': True, 'blank_id': 0}
        self.assertEqual(local_voice.encode_phonemes('Ab', config), [0, 1, 0, 2, 0])
        with self.assertRaises(ValueError):
            local_voice.encode_phonemes('', config)


if __name__ == '__main__':
    unittest.main()
