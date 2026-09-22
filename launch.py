"""Open an existing local instance, or start a new one."""
import os
import subprocess
import sys
import urllib.request
import webbrowser

url = 'http://127.0.0.1:' + os.environ.get('DUBBING_PORT', '8765')
try:
    with urllib.request.urlopen(url + '/api/info', timeout=2) as response:
        body = response.read()
    if b'id-ID-ArdiNeural' in body:
        webbrowser.open(url)
        sys.exit(0)
except OSError:
    pass
sys.exit(subprocess.call([sys.executable, 'app.py']))
