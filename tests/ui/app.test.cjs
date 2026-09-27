const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');

async function asset(route) {
  if (process.env.TEST_ASSET_BASE_URL) {
    const response = await fetch(process.env.TEST_ASSET_BASE_URL + route);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    return response.text();
  }
  return fs.readFile(path.join(__dirname, '../..', route === '/' ? 'static/index.html' : route.slice(1)), 'utf8');
}
const tick = () => new Promise(resolve => setImmediate(resolve));
async function boot(t) {
  const errors = [], calls = [];
  const console = new VirtualConsole();
  console.on('jsdomError', error => errors.push(error.message));
  const dom = new JSDOM(await asset('/'), {url:'http://127.0.0.1:8765/', runScripts:'outside-only', virtualConsole:console});
  t.after(() => dom.window.close());
  const w = dom.window, document = w.document;
  w.HTMLMediaElement.prototype.pause = function () {};
  w.HTMLMediaElement.prototype.load = function () {};
  w.HTMLMediaElement.prototype.play = async function () {};
  w.HTMLElement.prototype.scrollIntoView = function () {};
  w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  w.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new w.Event('close')); };
  w.setTimeout = w.setInterval = () => 1;
  w.confirm = () => true;
  const course = {id:'default', name:'Demo', videos:[], results:{}, available:true, status:'ready', count:0};
  const job = {id:'review-demo', title:'Demo', status:'review', phase:'prepare', language:'fr', language_name:'Prancis',
    tts:'supertonic', voice:'supertonic-F5', duration:5, progress:100, message:'Siap diperiksa', output_mode:'video',
    segments:[{start:0, end:5, en:'Hello.', id:'Bonjour.'}], warnings:[]};
  const historyJobs = Array.from({length:23}, (_,i) => ({...job, id:i===0?job.id:`demo-${i}`, title:`Project ${i+1}`}));
  const watchLists=[];
  w.fetch = async (url, options={}) => {
    calls.push({url, options});
    let result;
    if (url === '/api/info') result = {ffmpeg:true, supertonic:true, default_tts:'supertonic', default_language:'id', languages:{id:'Indonesia',fr:'Prancis'}};
    else if (url === '/api/playlists') result = [course];
    else if (url === '/api/playlists/default') result = course;
    else if (url === '/api/playlists/default/results') result = {};
    else if (url === '/api/jobs') result = [job];
    else if (url.startsWith('/api/history?')) {
      const query = new URL(url, 'http://localhost').searchParams;
      const pageSize = Number(query.get('page_size')), pages = Math.max(1,Math.ceil(historyJobs.length/pageSize));
      const page = Math.min(Number(query.get('page')),pages);
      result = {items:historyJobs.slice((page-1)*pageSize,page*pageSize),total:historyJobs.length,page,pages,page_size:pageSize};
    }
    else if (url.startsWith('/api/jobs/') && options.method==='DELETE') {
      historyJobs.splice(historyJobs.findIndex(item=>url===`/api/jobs/${item.id}`),1); result={ok:true};
    }
    else if (url.startsWith('/api/watch-playlists')) {
      if(options.method==='POST'){const data=JSON.parse(options.body);const list={id:'watch-1',name:data.name,job_ids:data.job_ids,items:historyJobs.filter(item=>data.job_ids.includes(item.id))};watchLists.push(list);result=list;}else result=watchLists;
    }
    else if (url === '/api/jobs/review-demo') result = job;
    else if (url === '/api/jobs/review-demo/save') {
      job.segments[0].id = JSON.parse(options.body).translations[0]; result = job;
    }
    else throw new Error('Unexpected API request: ' + url);
    return {ok:true, status:200, json:async () => result};
  };
  w.eval((await asset('/static/playback.js'))+';window.DubbingPlayback=DubbingPlayback;');
  w.eval(await asset('/static/app.js'));
  for (let i=0; i<5; i++) await tick();
  assert.equal(document.getElementById('notice').textContent, '');
  assert.deepEqual(errors, []);
  return {w, document, job, calls, errors, historyJobs};
}

test('startup exposes voice and Whisper dropdowns, with supported translators', async t => {
  const {document:d} = await boot(t);
  assert.equal(d.getElementById('voice').options.length, 10);
  for (const id of ['tts','model','translator','voice','language']) {
    assert.equal(d.getElementById(id).tagName, 'SELECT');
    assert.equal(d.getElementById(id).closest('details'), null);
  }
  assert.equal(d.getElementById('model').options.length, 3);
  assert.equal(d.getElementById('model').value, 'base');
  assert.deepEqual([...d.getElementById('translator').options].map(o=>o.value), ['local','google']);
  assert.equal(d.querySelector('#openRouterSettings, #openSettings, #settingsDialog'), null);
  const ids = [...d.querySelectorAll('[id]')].map(element => element.id);
  assert.equal(new Set(ids).size, ids.length);
});

test('opening and polling a review project renders language label and editable text', async t => {
  const {w, document:d, errors} = await boot(t);
  await w.openProject('review-demo');
  assert.equal(d.getElementById('notice').textContent, '');
  assert.equal(d.getElementById('review').classList.contains('hidden'), false);
  assert.match(d.getElementById('editorTargetLabel').textContent, /FR/);
  assert.equal(d.querySelector('#segments textarea').value, 'Bonjour.');
  assert.equal(d.getElementById('reviewVoice').value, 'supertonic-F5');
  d.querySelector('#segments textarea').value = 'Bienvenue.';
  d.querySelector('#segments textarea').oninput();
  await w.poll();
  assert.equal(d.querySelector('#segments textarea').value, 'Bienvenue.');
  await d.getElementById('save').onclick();
  assert.equal(d.getElementById('notice').textContent, '');
  assert.deepEqual(errors, []);
});

test('completed video and audio projects show selected-language subtitle downloads', async t => {
  const {w, document:d, job} = await boot(t);
  for (const mode of ['video','audio']) {
    w.showJob({...job, id:mode, status:'done', output_mode:mode});
    assert.equal(d.getElementById('result').classList.contains('hidden'), false);
    assert.ok(d.querySelector('#downloads a[href*="subtitle.fr.srt"]'));
    assert.match(d.getElementById('downloadVideo').href, mode==='audio' ? /hasil\.mp3/ : /hasil\.mp4/);
  }
});

test('History is a separate paginated page with delete and project navigation', async t => {
  const {w,document:d} = await boot(t);
  assert.equal(d.querySelector('aside #history'),null);
  assert.equal(d.querySelector('aside .history-label'),null);
  await d.getElementById('showHistory').onclick();
  assert.equal(d.getElementById('setup').classList.contains('hidden'),true);
  assert.equal(d.getElementById('historyPage').classList.contains('hidden'),false);
  assert.equal(d.querySelectorAll('#history .history-entry').length,10);
  assert.equal(d.getElementById('historyPrev').disabled,true);
  await d.getElementById('historyNext').onclick();
  assert.equal(d.querySelector('#history tr td:nth-child(2)').textContent,'Project 11');
  await d.getElementById('historyNext').onclick();
  assert.equal(d.querySelectorAll('#history .history-entry').length,3);
  assert.equal(d.getElementById('historyNext').disabled,true);
  await d.querySelector('#history .text-button').onclick();
  assert.equal(d.querySelectorAll('#history .history-entry').length,2);
  d.getElementById('historyPageSize').value='20';
  await d.getElementById('historyPageSize').onchange();
  assert.equal(d.querySelectorAll('#history .history-entry').length,20);
  await d.querySelector('#history .history-open').onclick();
  assert.equal(d.getElementById('historyPage').classList.contains('hidden'),true);
  assert.equal(d.getElementById('project').classList.contains('hidden'),false);
  assert.equal(d.getElementById('notice').textContent,'');
});

test('manual translation review saves without any grammar request', async t => {
  const {w, document:d, job, calls} = await boot(t);
  await w.openProject(job.id);
  assert.equal(d.querySelector('#grammarAll, #grammarDialog, #undoGrammar, .improve-text'), null);
  const area = d.querySelector('#segments textarea');
  area.value = 'Bonjour et bienvenue.';
  area.oninput();
  await d.getElementById('save').onclick();
  assert.equal(job.segments[0].id, 'Bonjour et bienvenue.');
  assert.ok(calls.every(call => !/\/grammar|\/improve\//.test(call.url)));
});

test('History table selects across pages and batch deletes only selected projects', async t => {
  const {w,document:d,calls,historyJobs}=await boot(t);await w.showHistoryPage();
  assert.equal(d.getElementById('history').tagName,'TBODY');
  let check=d.querySelector('#history input');check.checked=true;check.onchange();
  await d.getElementById('historyNext').onclick();
  check=d.querySelector('#history input');check.checked=true;check.onchange();
  assert.match(d.getElementById('historySelection').textContent,/2 dipilih/);
  await d.getElementById('historyDelete').onclick();
  assert.equal(historyJobs.length,21);
  assert.equal(calls.filter(call=>call.options.method==='DELETE').length,2);
  assert.match(d.getElementById('historySelection').textContent,/0 dipilih/);
});

test('History creates a persistent playlist view and supports sequential playback', async t => {
  const {w,document:d,historyJobs,calls,errors}=await boot(t);
  historyJobs.slice(0,2).forEach(item=>{item.status='done';item.media={mode:'video',media_url:'/result.mp4',download_url:'/result.mp4?download=1'};});
  await w.showHistoryPage();
  for(const check of [...d.querySelectorAll('#history input')].slice(0,2)){check.checked=true;check.onchange();}
  assert.equal(d.getElementById('historyPlaylist').disabled,false);
  await d.getElementById('historyPlaylist').onclick();
  d.getElementById('watchName').value='My lessons';await d.getElementById('watchCreateSave').onclick();
  assert.equal(d.getElementById('playlistPage').classList.contains('hidden'),false);
  assert.equal(d.getElementById('setup').classList.contains('hidden'),true);
  assert.match(d.getElementById('watchDetails').textContent,/My lessons/);
  assert.ok(d.querySelector('#watchDetails a[href="/api/watch-playlists/watch-1/download"]'));
  assert.match(d.getElementById('watchDetails').textContent,/Unduh semua/);
  const play=[...d.querySelectorAll('#watchDetails button')].find(button=>button.textContent==='Play semua');await play.onclick();
  assert.equal(d.getElementById('previewDialog').open,true);
  assert.equal(d.getElementById('watchPosition').textContent,'1 / 2');
  d.getElementById('previewVideo').dispatchEvent(new w.Event('ended'));await tick();
  assert.equal(d.getElementById('watchPosition').textContent,'2 / 2');
  assert.equal(d.getElementById('watchNext').disabled,true);
  d.getElementById('closePreview').onclick();
  assert.ok(calls.some(call=>call.url==='/api/watch-playlists' && call.options.method==='POST'));
  assert.deepEqual(errors,[]);
});

test('History deletion cancellation and partial failure preserve unremoved selections', async t => {
  const {w,document:d,historyJobs}=await boot(t);await w.showHistoryPage();
  const checks=[...d.querySelectorAll('#history input')].slice(0,2);for(const check of checks){check.checked=true;check.onchange();}
  w.confirm=()=>false;await d.getElementById('historyDelete').onclick();assert.equal(historyJobs.length,23);
  w.confirm=()=>true;const fetch=w.fetch;
  w.fetch=async(url,options)=>{if(options?.method==='DELETE' && url.endsWith('/demo-1'))throw new Error('File terkunci');return fetch(url,options);};
  await d.getElementById('historyDelete').onclick();assert.equal(historyJobs.length,22);
  assert.match(d.getElementById('notice').textContent,/1 gagal/);
  assert.match(d.getElementById('historySelection').textContent,/1 dipilih/);
});


test('Google API controls are removed and free Google remains selected', async t => {
 const {document:d}=await boot(t);assert.equal(d.querySelector('#googleSettings, #googleDialog'),null);assert.equal(d.getElementById('translator').value,'google');
});

test('History sort toggles direction, resets pagination, preserves selection and persists', async t => {
  const {w,document:d,calls}=await boot(t);await w.showHistoryPage();
  const check=d.querySelector('#history input');check.checked=true;check.onchange();
  await d.getElementById('historyNext').onclick();
  await d.querySelector('[data-history-sort="title"] button').onclick();
  assert.match(calls.at(-1).url,/page=1.*sort=title&direction=asc/);
  assert.equal(d.querySelector('[data-history-sort="title"]').getAttribute('aria-sort'),'ascending');
  await d.querySelector('[data-history-sort="title"] button').onclick();
  assert.match(calls.at(-1).url,/direction=desc/);
  assert.match(d.getElementById('historySelection').textContent,/1 dipilih/);
  assert.equal(JSON.parse(w.localStorage.getItem('history-sort')).direction,'desc');
  await d.getElementById('historyResetSort').onclick();
  assert.match(calls.at(-1).url,/sort=order&direction=desc/);
});

test('Playlist sorts natural names and duration, and playback follows displayed order', async t => {
  const {w,document:d,historyJobs}=await boot(t);
  historyJobs.slice(0,2).forEach((item,i)=>{item.title=i?'Lesson 2':'Lesson 10';item.duration=i?10:100;item.status='done';item.media={mode:'video',media_url:'/result.mp4',download_url:'/result.mp4'};});
  await w.showHistoryPage();
  for(const check of [...d.querySelectorAll('#history input')].slice(0,2)){check.checked=true;check.onchange();}
  await d.getElementById('historyPlaylist').onclick();d.getElementById('watchName').value='Sorted';await d.getElementById('watchCreateSave').onclick();
  await d.querySelector('[data-watch-sort="title"] button').onclick();
  assert.equal(d.querySelector('#watchDetails tbody tr td:nth-child(2)').textContent,'Lesson 2');
  const play=[...d.querySelectorAll('#watchDetails button')].find(b=>b.textContent==='Play semua');await play.onclick();
  assert.equal(d.getElementById('previewTitle').textContent,'Lesson 2');
  d.getElementById('closePreview').onclick();
  await d.querySelector('[data-watch-sort="duration"] button').onclick();
  await d.querySelector('[data-watch-sort="duration"] button').onclick();
  assert.equal(d.querySelector('#watchDetails tbody tr td:nth-child(2)').textContent,'Lesson 10');
  assert.equal(d.querySelector('[data-watch-sort="duration"]').getAttribute('aria-sort'),'descending');
});
