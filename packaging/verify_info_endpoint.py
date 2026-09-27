"""Verify startup and language discovery from a built EXE using isolated data."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


exe = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='dubbing-info-') as temporary:
    data = Path(temporary) / 'data'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = dict(os.environ, DUBBING_DATA=str(data), DUBBING_PORT=str(port),
               DUBBING_LIBRARY=str(Path(temporary) / 'library'))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (Path(temporary) / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(exe), '--no-browser'], env=env,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Packaged application exited during startup')
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/info', timeout=2) as response:
                        info = json.load(response)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.5)
            assert info['storage_id'] == hashlib.sha256(str(data.resolve()).casefold().encode()).hexdigest()
            assert info['default_language'] == 'id'
            assert info['languages']['id'] == 'Indonesia'
            assert len(info['languages']) == 30
            assert len([voice for voice in info['voices'] if voice.startswith('supertonic-')]) == 10
            assert info['supertonic'] and info['default_tts'] == 'supertonic'
            with opener.open(f'http://127.0.0.1:{port}/api/history?page=1&page_size=10', timeout=5) as response:
                history = json.load(response)
            assert history['items'] == [] and history['page'] == 1 and history['pages'] == 1
            for removed in ('/api/settings', '/api/openrouter/models', '/api/google/settings'):
                try:
                    opener.open(f'http://127.0.0.1:{port}'+removed, timeout=5)
                    raise AssertionError('Removed endpoint still available: '+removed)
                except urllib.error.HTTPError as error:
                    assert error.code == 404
            print('PASS: packaged History pagination and removed translation API endpoints.')
            print('PASS: packaged /api/info HTTP 200; 30 languages; 10 Supertonic voices; isolated data.')
            if '--ui' in sys.argv:
                ui_tests = Path(__file__).resolve().parents[1] / 'tests' / 'ui' / 'app.test.cjs'
                ui_result = subprocess.run(['node', '--test', str(ui_tests)],
                               env=dict(os.environ, TEST_ASSET_BASE_URL=f'http://127.0.0.1:{port}'),
                               creationflags=subprocess.CREATE_NO_WINDOW,
                               capture_output=True, text=True, encoding='utf-8')
                print(ui_result.stdout)
                if ui_result.stderr:
                    print(ui_result.stderr)
                ui_result.check_returncode()
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, check=True)
                process.wait(timeout=20)
