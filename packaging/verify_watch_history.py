"""Verify real EXE endpoints with disposable fixture files, including restart."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


exe=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='dubbing-watch-') as temporary:
    root=Path(temporary)
    data=root/'data';data.mkdir()
    source=root/'external-source.mp4';source.write_bytes(b'original fixture')
    for index in range(3):
        key=str(index);directory=data/key;directory.mkdir()
        (directory/'hasil.mp4').write_bytes(b'output fixture '+key.encode())
        (directory/'job.json').write_text(json.dumps(dict(id=key,title='Lesson '+key,status='done',
            directory=str(directory),source=str(source),output_mode='video',language='id')))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    env=dict(os.environ,DUBBING_DATA=str(data),DUBBING_LIBRARY=str(root/'library'),DUBBING_PORT=str(port))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(route, body=None, method=None, raw=False):
        req=urllib.request.Request(f'http://127.0.0.1:{port}/api/'+route,
            data=json.dumps(body).encode() if body is not None else None,method=method,
            headers={'Content-Type':'application/json','X-Dubbing-Studio':'1'})
        with opener.open(req,timeout=20) as response:
            payload=response.read()
            return payload if raw else json.loads(payload)
    process=None
    def stop():
        if process and process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            process.wait(timeout=20)
    with (root/'server.log').open('w',encoding='utf-8') as log:
        def start():
            global process
            process=subprocess.Popen([str(exe),'--no-browser'],env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+90
            while True:
                if process.poll() is not None:raise RuntimeError('EXE exited')
                try:request('info');return
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.3)
        try:
            start()
            playlist=request('watch-playlists',{'name':'Saved lessons','job_ids':['1','0','2']})
            key=playlist['id']
            archive=request('watch-playlists/'+key+'/download',raw=True)
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                assert len(bundle.namelist())==3
                assert bundle.read(bundle.namelist()[0])==b'output fixture 1'
            stop();start()
            assert request('watch-playlists')[0]['job_ids']==['1','0','2']
            for job_id in ['1','0']:
                request('jobs/'+job_id,method='DELETE')
                assert not (data/job_id).exists()
            assert source.exists()
            assert request('history')['total']==1
            assert request('watch-playlists')[0]['job_ids']==['2']
            request('watch-playlists/'+key,method='DELETE')
            assert (data/'2'/'hasil.mp4').exists()
            assert request('watch-playlists')==[]
            print('PASS: EXE playlist creation, ZIP bytes, restart persistence, selected project file deletion, playlist cleanup, external source preservation.')
        finally:
            stop()
