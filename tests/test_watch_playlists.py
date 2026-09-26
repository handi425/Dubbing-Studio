import json
import io
import zipfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app


class WatchPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.data=self.root/'data';self.data.mkdir()
        self.source=self.root/'original.mp4';self.source.write_bytes(b'original')
        self.jobs={}
        for index in range(3):
            key=str(index);directory=self.data/key;directory.mkdir()
            (directory/'hasil.mp4').write_bytes(b'rendered output')
            job=dict(id=key,title='Lesson '+key,status='done',directory=str(directory),source=str(self.source),output_mode='video')
            self.jobs[key]=job
            (directory/'job.json').write_text(json.dumps(job))
        for key,value in [('DATA',self.data),('jobs',self.jobs)]:
            mock=patch.object(app,key,value);mock.start();self.addCleanup(mock.stop)
        self.client=app.app.test_client()
        self.headers={'X-Dubbing-Studio':'1'}

    def post(self,path,body):
        return self.client.post('/api/'+path,json=body,headers=self.headers)

    def test_create_append_deduplicate_rename_remove_and_reload(self):
        response=self.post('watch-playlists',{'name':'Lessons','job_ids':['1','0','1']})
        self.assertEqual(response.status_code,200)
        key=response.json['id']
        self.assertEqual(response.json['job_ids'],['1','0'])
        response=self.post('watch-playlists/'+key,{'name':'Renamed','job_ids':['2','1']})
        self.assertEqual(response.json['job_ids'],['1','0','2'])
        self.post('watch-playlists/'+key,{'remove_ids':['0']})
        saved=self.client.get('/api/watch-playlists').json[0]
        self.assertEqual(saved['name'],'Renamed')
        self.assertEqual(saved['job_ids'],['1','2'])
        self.assertNotIn('source',saved['items'][0])
        self.assertTrue(saved['items'][0]['media'])
        self.assertEqual(app.read_watchlists()[0]['job_ids'],['1','2'])

    def test_delete_project_removes_actual_files_and_playlist_reference_only(self):
        self.post('watch-playlists',{'name':'Lessons','job_ids':['0','1']})
        for key in ['0','1']:
            response=self.client.delete('/api/jobs/'+key,headers=self.headers)
            self.assertEqual(response.status_code,200)
            self.assertFalse((self.data/key).exists())
            self.assertNotIn(key,app.jobs)
        self.assertEqual(self.client.get('/api/history').json['total'],1)
        self.assertEqual(app.read_watchlists()[0]['job_ids'],[])
        self.assertTrue(self.source.exists())
        self.assertTrue((self.data/'2'/'hasil.mp4').exists())

    def test_delete_playlist_keeps_projects_and_files(self):
        key=self.post('watch-playlists',{'name':'Lessons','job_ids':['0']}).json['id']
        self.assertEqual(self.client.delete('/api/watch-playlists/'+key,headers=self.headers).status_code,200)
        self.assertEqual(app.read_watchlists(),[])
        self.assertTrue((self.data/'0'/'hasil.mp4').exists())
        self.assertIn('0',app.jobs)

    def test_batch_download_zip_has_unique_names_and_only_available_results(self):
        self.jobs['0']['title']=self.jobs['1']['title']='Same title'
        key=self.post('watch-playlists',{'name':'Lessons','job_ids':['0','1','2']}).json['id']
        self.jobs['2']['status']='review'
        with self.client.get('/api/watch-playlists/'+key+'/download', buffered=True) as response:
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,'application/zip')
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(archive.namelist(),['0001-Same_title.mp4','0002-Same_title.mp4'])
                self.assertEqual(archive.read(archive.namelist()[0]),b'rendered output')
        self.assertTrue((self.data/'0'/'hasil.mp4').exists())
        for job in self.jobs.values():job['status']='review'
        self.assertEqual(self.client.get('/api/watch-playlists/'+key+'/download').status_code,409)

    def test_validation_and_unavailable_outputs(self):
        self.jobs['1']['status']='rendering'
        for body in [{'name':'','job_ids':['0']},{'name':'Okay','job_ids':[]},{'name':'Okay','job_ids':['1']},{'name':'Okay','job_ids':[{}]}]:
            self.assertEqual(self.post('watch-playlists',body).status_code,400)
        self.assertEqual(self.client.delete('/api/jobs/1',headers=self.headers).status_code,409)
        self.assertTrue((self.data/'1').exists())
        key=self.post('watch-playlists',{'name':'Lessons','job_ids':['0']}).json['id']
        (self.data/'0'/'hasil.mp4').unlink()
        self.assertIsNone(self.client.get('/api/watch-playlists').json[0]['items'][0]['media'])
        self.assertEqual(self.post('watch-playlists/'+key,{'job_ids':['2','1']}).status_code,400)
        self.assertEqual(app.read_watchlists()[0]['job_ids'],['0'])
