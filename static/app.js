const $ = id => document.getElementById(id);
let library = [], selectedPath = '', sourceMode = 'library', activeId = null, currentJob = null, dirty = false, timer = null, editorId = null;
const activeStates = ['queued', 'preparing', 'rendering'];
const escapeHTML = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message) { $('notice').textContent = message; $('notice').classList.toggle('hidden', !message); }
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'X-Dubbing-Studio':'1'}};
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const response = await fetch('/api/' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Permintaan gagal.');
  return data;
}
function renderLibrary() {
  const query = $('search').value.toLowerCase();
  const filtered = library.filter(v => (v.name + v.folder).toLowerCase().includes(query));
  $('library').innerHTML = '';
  let folder = null;
  for (const video of filtered) {
    if (folder !== video.folder) { const label = document.createElement('div'); label.className = 'folder-label'; label.textContent = video.folder; $('library').append(label); folder = video.folder; }
    const button = document.createElement('button');
    button.className = 'video-item' + (video.path === selectedPath ? ' selected' : '');
    button.title = video.name;
    button.setAttribute('aria-pressed', video.path === selectedPath);
    button.innerHTML = `<span class="video-symbol">▷</span><span class="video-text"><strong>${escapeHTML(video.name.replace(/^CHP\s+\d+\s+/i,''))}</strong><small>${video.size_mb} MB · ${video.subtitle ? 'Subtitle Inggris tersedia' : 'Transkripsi otomatis'}</small></span><span class="video-select"></span>`;
    button.onclick = () => { selectedPath = video.path; renderLibrary(); };
    $('library').append(button);
  }
  if (!filtered.length) $('library').innerHTML = '<p class="muted">Tidak ada video yang cocok. Anda juga bisa mengunggah video sendiri.</p>';
}
document.querySelectorAll('[data-source]').forEach(button => button.onclick = () => {
  sourceMode = button.dataset.source;
  document.querySelectorAll('[data-source]').forEach(b => b.classList.toggle('selected', b === button));
  $('libraryPanel').classList.toggle('hidden', sourceMode !== 'library');
  $('uploadPanel').classList.toggle('hidden', sourceMode !== 'upload');
});
$('search').oninput = renderLibrary;
document.querySelectorAll('[name=voice]').forEach(input => input.onchange = () => document.querySelectorAll('.voice-choice').forEach(label => label.classList.toggle('selected', label.querySelector('input').checked)));
$('rate').oninput = () => $('rateValue').textContent = +$('rate').value === 0 ? 'Normal' : `${+$('rate').value > 0 ? '+' : ''}${$('rate').value}%`;
$('tts').onchange = () => $('voiceProvider').textContent = $('tts').value === 'wikidepia' ? 'Bahasa Indonesia · Wikidepia lokal (data suara Azure)' : 'Bahasa Indonesia · Microsoft Neural';
$('videoFile').onchange = () => $('uploadName').textContent = $('videoFile').files[0]?.name || '';
['dragover','dragleave','drop'].forEach(event => $('dropzone').addEventListener(event, e => { e.preventDefault(); $('dropzone').classList.toggle('drag', event === 'dragover'); if (event === 'drop' && e.dataTransfer.files.length) { const dt = new DataTransfer(); dt.items.add(e.dataTransfer.files[0]); $('videoFile').files = dt.files; $('videoFile').onchange(); } }));
function settings() { return {voice: document.querySelector('[name=voice]:checked').value, rate:$('rate').value, original_volume:$('volume').value, tts:$('tts').value, translator:$('translator').value, model:$('model').value}; }
$('start').onclick = async () => {
  notice('');
  if (sourceMode === 'library' && !selectedPath) return notice('Pilih satu video dari pustaka kursus.');
  if (sourceMode === 'upload' && !$('videoFile').files.length) return notice('Pilih video yang ingin diterjemahkan.');
  const form = new FormData(); Object.entries(settings()).forEach(([k,v]) => form.append(k,v));
  if (sourceMode === 'library') form.append('library_path', selectedPath); else form.append('video', $('videoFile').files[0]);
  if ($('subtitleFile').files.length) form.append('subtitle', $('subtitleFile').files[0]);
  $('start').disabled = true; $('start').textContent = sourceMode === 'upload' ? 'Mengunggah video…' : 'Menyiapkan video…';
  try { const job = await api('jobs', form); dirty = false; await openProject(job.id); await history(); }
  catch (error) { notice(error.message); }
  finally { $('start').disabled = false; $('start').innerHTML = 'Terjemahkan video <span>→</span>'; }
};
function timestamp(n) { const sec = Math.floor(n); return `${Math.floor(sec/60).toString().padStart(2,'0')}:${(sec%60).toString().padStart(2,'0')}`; }
function showJob(job) {
  currentJob = job;
  const busy = activeStates.includes(job.status);
  $('projectTitle').textContent = job.title; $('statusText').textContent = job.message;
  $('percent').textContent = `${Math.round(job.progress || 0)}%`; $('progressBar').style.width = `${job.progress || 0}%`;
  $('cancel').classList.toggle('hidden', !busy);
  $('retry').classList.toggle('hidden', !['error','cancelled','interrupted'].includes(job.status));
  $('jobError').textContent = job.error || ''; $('jobError').classList.toggle('hidden', !job.error);
  $('step1').classList.remove('current'); $('step2').classList.toggle('current', job.phase !== 'render'); $('step3').classList.toggle('current', job.phase === 'render');
  const editable = job.segments?.length > 0 && !busy;
  $('review').classList.toggle('hidden', !editable);
  if (editable && editorId !== job.id) {
    let voiceTools = $('reviewVoiceTools');
    if (!voiceTools) {
      voiceTools = document.createElement('div'); voiceTools.id = 'reviewVoiceTools'; voiceTools.className = 'review-voice-tools';
      voiceTools.innerHTML = '<label>Suara<select id="reviewVoice"><option value="id-ID-ArdiNeural">Ardi</option><option value="id-ID-GadisNeural">Gadis</option></select></label><label>Mesin suara<select id="reviewTts"></select></label>';
      $('segments').parentNode.insertBefore(voiceTools, $('segments').parentNode.querySelector('.editor-toolbar'));
      voiceTools.querySelectorAll('select').forEach(select => select.onchange = () => { dirty = true; $('save').textContent = 'Simpan perubahan'; });
    }
    $('reviewTts').innerHTML = $('tts').innerHTML;
    $('reviewVoice').value = job.voice; $('reviewTts').value = job.tts;
    $('segments').innerHTML = job.segments.map((s,i) => `<div class="segment"><time>${timestamp(s.start)}<br>${timestamp(s.end)}</time><p>${escapeHTML(s.en)}</p><textarea aria-label="Terjemahan bagian ${i+1}" data-index="${i}">${escapeHTML(s.id)}</textarea></div>`).join('');
    $('segments').querySelectorAll('textarea').forEach(area => area.oninput = () => { dirty = true; $('save').textContent = 'Simpan perubahan'; });
    $('segmentCount').textContent = `${job.segments.length} bagian · ${timestamp(job.duration)} durasi video`;
    editorId = job.id;
  }
  $('result').classList.toggle('hidden', job.status !== 'done');
  if (job.status === 'done') {
    const base = `/api/jobs/${job.id}/files/`;
    if ($('player').dataset.job !== job.id) {
      $('player').src = base + 'hasil.mp4'; $('player').innerHTML = `<track kind="subtitles" src="${base}subtitle.id.vtt" srclang="id" label="Indonesia" default><track kind="subtitles" src="${base}subtitle.en.vtt" srclang="en" label="English">`;
      $('player').dataset.job = job.id;
    }
    $('downloadVideo').href = base + 'hasil.mp4?download=1';
    $('downloads').innerHTML = [['subtitle.id.srt','Subtitle Indonesia'],['subtitle.en.srt','Subtitle Inggris'],['transkrip.txt','Transkrip bilingual']].map(([name,label]) => `<a href="${base}${name}?download=1" download>${label} ↓</a>`).join('');
  }
  const warnings = job.warnings || []; $('warnings').classList.toggle('hidden', !warnings.length); $('warnings').textContent = warnings.join('\n');
}
async function poll() {
  if (!activeId) return;
  const id = activeId;
  try { const job = await api(`jobs/${id}`); if (activeId !== id) return; showJob(job); if (activeStates.includes(job.status)) timer = setTimeout(poll, 1600); else await history(); }
  catch (error) { notice(error.message + ' Mencoba menghubungkan kembali…'); if (activeId === id) timer = setTimeout(poll, 5000); }
}
async function leaveEdits() { if (dirty && activeId) await saveTexts(); }
async function openProject(id) {
  await leaveEdits(); clearTimeout(timer); activeId = id; editorId = null;
  $('setup').classList.add('hidden'); $('project').classList.remove('hidden'); notice('');
  await poll();
}
async function newProject() {
  try { await leaveEdits(); clearTimeout(timer); activeId = null; $('player').pause(); $('setup').classList.remove('hidden'); $('project').classList.add('hidden'); $('step1').classList.add('current'); $('step2').classList.remove('current'); $('step3').classList.remove('current'); notice(''); }
  catch (error) { notice(error.message); }
}
$('back').onclick = newProject; $('newProject').onclick = newProject;
async function history() {
  const projects = await api('jobs'); $('history').innerHTML = '';
  if (!projects.length) $('history').innerHTML = '<p class="muted">Proyek Anda akan muncul di sini.</p>';
  projects.forEach(job => { const button = document.createElement('button'); button.textContent = (job.status === 'done' ? '✓ ' : '◷ ') + job.title; button.title = job.title; button.onclick = () => openProject(job.id).catch(e => notice(e.message)); $('history').append(button); });
}
async function saveTexts() {
  const texts = [...$('segments').querySelectorAll('textarea')].map(t => t.value);
  const job = await api(`jobs/${activeId}/save`, {translations:texts, voice:$('reviewVoice').value, tts:$('reviewTts').value});
  dirty = false; $('save').textContent = 'Tersimpan ✓'; return job;
}
$('save').onclick = async () => { try { $('save').disabled = true; const job = await saveTexts(); showJob(job); } catch(e) { notice(e.message); } finally { $('save').disabled = false; } };
$('render').onclick = async () => {
  try { $('render').disabled = true; notice(''); await saveTexts(); const job = await api(`jobs/${activeId}/render`, {}); $('player').pause(); $('player').removeAttribute('data-job'); showJob(job); clearTimeout(timer); timer = setTimeout(poll, 1000); }
  catch(e) { notice(e.message); } finally { $('render').disabled = false; }
};
$('retry').onclick = async () => { try { if(dirty) await saveTexts(); await api(`jobs/${activeId}/retry`, {}); clearTimeout(timer); await poll(); } catch(e) { notice(e.message); } };
$('cancel').onclick = async () => { try { await api(`jobs/${activeId}/cancel`, {}); } catch(e) { notice(e.message); } };
window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
(async () => {
  try { const [videos, info] = await Promise.all([api('library'),api('info')]); library = videos; $('videoCount').textContent = videos.length; renderLibrary(); await history();
    if (!info.ffmpeg) notice('FFmpeg belum tersedia. Pasang FFmpeg dan tambahkan folder bin ke PATH sebelum memproses video.');
    $('tts').querySelector('[value=azure]').disabled = !info.azure_speech; $('translator').querySelector('[value=azure]').disabled = !info.azure_translator;
    $('tts').querySelector('[value=wikidepia]').disabled = !info.wikidepia;
  } catch(e) { notice(e.message); }
})();
