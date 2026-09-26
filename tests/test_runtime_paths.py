import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_paths


class RuntimePathTests(unittest.TestCase):
    def test_source_keeps_existing_data(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, 'FROZEN', False):
            self.assertEqual(runtime_paths.data_directory(), runtime_paths.BASE / 'data')

    def test_frozen_data_is_outside_temporary_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'LOCALAPPDATA': directory}, clear=True), patch.object(runtime_paths, 'FROZEN', True):
                self.assertEqual(runtime_paths.data_directory(), Path(directory) / 'DubbingStudio' / 'data')

    def test_explicit_data_location_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'DUBBING_DATA': directory}, clear=True), patch.object(runtime_paths, 'FROZEN', True):
                self.assertEqual(runtime_paths.data_directory(), Path(directory).resolve())

    def test_configure_uses_bundled_tools_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'PATH': 'existing-tools'}, clear=True), \
                    patch.object(runtime_paths, 'FROZEN', True), \
                    patch.object(runtime_paths, 'DATA', root / 'data'), \
                    patch.object(runtime_paths, 'LIBRARY', root / 'Kursus'), \
                    patch.object(runtime_paths, 'RESOURCES', root / 'bundle'):
                runtime_paths.configure()
                first_path = os.environ['PATH']
                runtime_paths.configure()
                self.assertEqual(os.environ['PATH'], first_path)
                self.assertEqual(first_path.split(os.pathsep)[0], str(root / 'bundle' / 'bin'))
                self.assertTrue((root / 'data').is_dir())
                self.assertTrue((root / 'Kursus').is_dir())
                self.assertEqual(os.environ['HF_HOME'], str(root / 'data/models/huggingface'))
