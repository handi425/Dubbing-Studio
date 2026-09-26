import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import engine
import local_voice
import supertonic_voice


class SupertonicTests(unittest.TestCase):
    def test_default_voice_and_provider_compatibility(self):
        with patch.object(supertonic_voice, 'ready', return_value=True):
            self.assertEqual(app.options({})['tts'], 'supertonic')
            self.assertEqual(app.options({})['voice'], 'supertonic-M1')
            self.assertEqual(app.options({'voice': 'supertonic-F1'})['voice'], 'supertonic-F1')
            self.assertEqual(app.options({'tts': 'edge'})['voice'], 'id-ID-ArdiNeural')
            for selection in [{'tts': 'edge', 'voice': 'supertonic-F1'},
                              {'tts': 'supertonic', 'voice': 'id-ID-ArdiNeural'}]:
                with self.assertRaisesRegex(ValueError, 'sesuai'):
                    app.options(selection)
            response = app.app.test_client().get('/api/info')
            self.assertEqual(response.status_code, 200)
            info = response.json
            self.assertEqual(info['languages'], supertonic_voice.LANGUAGES)
            self.assertEqual(info['default_language'], 'id')
            self.assertEqual(info['default_tts'], 'supertonic')
            self.assertTrue(info['supertonic'])

    def test_missing_model_is_reported_without_cloud_fallback(self):
        with patch.object(supertonic_voice, 'ready', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Supertonic 3 belum tersedia'):
                app.options({'tts': 'supertonic'})

    def test_source_and_frozen_worker_dispatch_and_cache(self):
        for frozen in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                job = dict(directory=directory, tts='supertonic', voice='supertonic-F1', rate=15,
                           segments=[{'id': 'Halo.'}, {'id': 'Halo.'}])
                def run(command, report, timeout):
                    self.assertIn('--supertonic-worker' if frozen else 'supertonic_voice.py',
                                  command if frozen else Path(command[-2]).name)
                    manifest = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
                    self.assertEqual(manifest['voice'], 'supertonic-F1')
                    self.assertEqual(manifest['rate'], 15)
                    self.assertEqual(len(manifest['items']), 1)
                    self.assertEqual(Path(manifest['model']), supertonic_voice.model_directory())
                    report()
                    Path(manifest['items'][0]['target']).write_bytes(b'completed')
                with patch.object(supertonic_voice, 'ready', return_value=True), \
                        patch.object(local_voice, 'FROZEN', frozen), patch.object(engine, 'run', side_effect=run) as runner:
                    supertonic_voice.generate(job, lambda **kw: None, lambda: None)
                    supertonic_voice.generate(job, lambda **kw: None, lambda: None)
                    self.assertEqual(runner.call_count, 1)


if __name__ == '__main__':
    unittest.main()
