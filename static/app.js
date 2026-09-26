const $ = id => document.getElementById(id);
let library = [], selectedPaths = new Set(), sourceMode = 'library', activeId = null, currentJob = null, dirty = false, timer = null, editorId = null;
let playlists = [], playlistId = null, loadingCourse = false, importing = false, stopImport = false, resumeCourse = null, courseRequest = 0;
let libraryResults = {}, resultRefreshBusy = false, previewPlayback = null;
let historyPageNumber = 1, historyLoad = 0;
const historySelected=new Map();
let historyVisible=[], watchLists=[], watchId=null, watchQueue=[], watchIndex=0;
const activeStates = ['queued', 'preparing', 'rendering'];
const escapeHTML = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message) { $('notice').textContent = message; $('notice').classList.toggle('hidden', !message); }
async function api(path, body, signal) {
  const options = body === undefined ? {} : {method:body?.method || 'POST', headers:{'X-Dubbing-Studio':'1'}};
  if (signal) options.signal=signal;
  if (body?.method === 'DELETE') body = undefined;
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const response = await fetch('/api/' + path, options);
  if (response.status === 404 && path === 'playlists') throw new Error('Fitur playlist membutuhkan server terbaru. Tutup server Dubbing Studio, jalankan kembali MULAI DUBBING.bat, lalu refresh browser.');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Permintaan gagal.');
  return data;
}
function switchSource(mode) {
  sourceMode = mode;
  document.querySelectorAll('[data-source]').forEach(b => b.classList.toggle('selected', b.dataset.source === mode));
  $('libraryPanel').classList.toggle('hidden', mode !== 'library');
  $('uploadPanel').classList.toggle('hidden', mode !== 'upload');
  updateSelection();
}
function renderPlaylists() {
  const query = $('courseSearch').value.toLowerCase();
  $('playlists').innerHTML = '';
  for (const course of playlists.filter(c => c.name.toLowerCase().includes(query))) {
    const button = document.createElement('button');
    button.className = 'playlist-card' + (course.id === playlistId ? ' selected' : '');
    button.setAttribute('aria-pressed', course.id === playlistId);
    const state = course.status === 'importing' ? 'Impor belum selesai · klik untuk melanjutkan' : !course.available ? 'Folder tidak tersedia' : `${course.count} video · ${course.kind === 'upload' ? 'Disimpan di aplikasi' : 'Folder lokal'}`;
    button.innerHTML = `<strong>${escapeHTML(course.name)}</strong><small>${escapeHTML(state)}</small>`;
    button.onclick = () => {
      if (importing) return notice('Tunggu hingga impor selesai atau hentikan impor terlebih dahulu.');
      if (course.status === 'importing') {
        resumeCourse = course;
        $('courseFolder').value = ''; $('importFolder').disabled = true;
        $('courseName').value = course.name;
        $('importStatus').textContent = `Lanjutkan impor ${course.name}: pilih kembali folder kursus yang sama. File yang sudah tersimpan akan diperbarui.`;
        switchSource('upload');
      } else loadCourse(course.id).catch(e => notice(e.message));
    };
    if (course.id !== 'default') {
      const row = document.createElement('div'); row.className='playlist-row'; row.append(button);
      const remove=document.createElement('button'); remove.className='text-button'; remove.textContent='Hapus';
      remove.onclick=async event=>{event.stopPropagation();if(!confirm(`Hapus playlist ?${course.name}?? Folder video lokal tidak akan dihapus.`))return;try{await api(`playlists/${course.id}`,{method:'DELETE'});await refreshPlaylists();if(playlistId===course.id)await loadCourse('default');}catch(error){notice(error.message);}};
      row.append(remove); $('playlists').append(row);
    } else $('playlists').append(button);
  }
  if (!$('playlists').children.length) $('playlists').innerHTML = '<p class="muted">Tidak ada playlist yang cocok.</p>';
}
async function refreshPlaylists() {
  playlists = await api('playlists');
  $('videoCount').textContent = playlists.length + ' paket';
  renderPlaylists();
}
async function loadCourse(id, refresh = false) {
  const requestId = ++courseRequest;
  loadingCourse = true; selectedPaths.clear(); library = []; libraryResults = {}; playlistId = id;
  $('courseTitle').textContent = playlists.find(c => c.id === id)?.name || 'Playlist';
  $('courseStatus').textContent = 'Memuat video dan bab…'; $('refreshCourse').disabled = true;
  renderPlaylists(); renderLibrary(); notice('');
  try {
    const course = await api(`playlists/${id}${refresh ? '/refresh' : ''}`, refresh ? {} : undefined);
    if (requestId !== courseRequest) return;
    library = course.videos;
    libraryResults = course.results || {};
    const index = playlists.findIndex(c => c.id === id); if (index >= 0) playlists[index] = course;
    $('courseTitle').textContent = course.name;
    $('courseStatus').textContent = course.available ? `${library.length} video · ${new Set(library.map(v => v.folder)).size} bagian. Pilih video atau pilih semua hasil.` : 'Folder asal tidak tersedia. Sambungkan drive lalu klik Pindai ulang.';
    try { localStorage.setItem('dubbing-playlist', id); } catch (_) {}
    renderPlaylists(); renderLibrary();
  } catch (e) {
    if (requestId === courseRequest) { $('courseStatus').textContent = e.message; notice(e.message); }
  } finally {
    if (requestId === courseRequest) { loadingCourse = false; $('refreshCourse').disabled = false; }
  }
}
$('courseSearch').oninput = renderPlaylists;
$('refreshCourse').onclick = () => { if (playlistId) loadCourse(playlistId, true); };
$('addCourse').onclick = () => {
  if (!importing) { resumeCourse = null; $('courseName').value = ''; $('importStatus').textContent = ''; }
  switchSource('upload');
};
function importBusy(value) {
  importing = value;
  ['registerFolder', 'courseFolder', 'courseName', 'folderPath', 'importFolder'].forEach(id => $(id).disabled = value);
  $('importFolder').disabled = value || !$('courseFolder').files.length;
  $('cancelImport').classList.toggle('hidden', !value);
}
$('registerFolder').onclick = async () => {
  notice(''); importBusy(true); $('cancelImport').classList.add('hidden');
  $('importStatus').textContent = 'Memindai folder dan seluruh subfolder…';
  try {
    const course = await api('playlists', {folder: $('folderPath').value, name: $('courseName').value});
    await refreshPlaylists(); await loadCourse(course.id); switchSource('library');
    $('importStatus').textContent = 'Folder terdaftar. Playlist tersimpan untuk penggunaan berikutnya.';
  } catch (e) { $('importStatus').textContent = e.message; notice(e.message); }
  finally { importBusy(false); }
};
const videoPattern = /\.(mp4|mkv|mov|webm|avi|m4v)$/i;
function folderFiles() { return [...$('courseFolder').files].filter(f => /\.(mp4|mkv|mov|webm|avi|m4v|srt|vtt)$/i.test(f.name)); }
$('courseFolder').onchange = () => {
  const files = folderFiles(); const count = files.filter(f => videoPattern.test(f.name)).length;
  $('importStatus').textContent = `${count} video dan ${files.length - count} subtitle terdeteksi di seluruh subfolder. ${resumeCourse ? 'Melanjutkan playlist ' + resumeCourse.name + '.' : 'Klik Simpan sebagai playlist untuk mengimpor.'}`;
  $('importFolder').disabled = !count;
};
$('cancelImport').onclick = () => { stopImport = true; $('importStatus').textContent = 'Menghentikan setelah file saat ini tersimpan. Impor bisa dilanjutkan dari daftar playlist.'; };
$('importFolder').onclick = async () => {
  const files = folderFiles();
  if (!files.some(f => videoPattern.test(f.name))) return notice('Folder ini tidak berisi format video yang didukung.');
  if (files.some(f => f.size >= 8 * 1024 ** 3)) return notice('Ada file berukuran 8 GB atau lebih. Gunakan Daftarkan folder agar tidak perlu mengunggah.');
  if (files.some(f => /\.(srt|vtt)$/i.test(f.name) && f.size > 5 * 1024 ** 2)) return notice('Ukuran subtitle maksimal 5 MB.');
  const rootName = files[0].webkitRelativePath.split('/')[0];
  if (resumeCourse?.source_folder && resumeCourse.source_folder !== rootName) return notice(`Pilih kembali folder “${resumeCourse.source_folder}” untuk melanjutkan playlist ini. Untuk kursus lain, gunakan + Folder kursus.`);
  const name = $('courseName').value.trim() || rootName;
  importBusy(true); stopImport = false; notice('');
  $('importProgress').classList.remove('hidden'); $('importProgress').max = files.length; $('importProgress').value = 0;
  try {
    if (!resumeCourse) resumeCourse = await api('playlists', {kind:'upload', name, source_folder:rootName});
    for (let i = 0; i < files.length; i++) {
      if (stopImport) break;
      const file = files[i]; const relative = file.webkitRelativePath.split('/').slice(1).join('/');
      $('importStatus').textContent = `Mengimpor ${i + 1}/${files.length}: ${relative}`;
      const form = new FormData(); form.append('path', relative); form.append('file', file);
      await api(`playlists/${resumeCourse.id}/files`, form);
      $('importProgress').value = i + 1;
    }
    if (stopImport) { $('importStatus').textContent = 'Impor dihentikan. Pilih playlist ini nanti untuk melanjutkan dari folder yang sama.'; await refreshPlaylists(); return; }
    const course = await api(`playlists/${resumeCourse.id}/finish`, {});
    resumeCourse = null; $('courseFolder').value = '';
    await refreshPlaylists(); await loadCourse(course.id); switchSource('library');
    notice(`Playlist “${course.name}” tersimpan dengan ${course.count} video. Pilih video untuk diterjemahkan atau dibuat audio.`);
  } catch (e) { notice(e.message); $('importStatus').textContent = 'Impor belum selesai: ' + e.message + ' Klik Simpan sebagai playlist untuk mencoba lagi.'; await refreshPlaylists().catch(() => {}); }
  finally { importBusy(false); }
};
function renderLibrary() {
  const query = $('search').value.toLowerCase();
  const filtered = library.filter(v => (v.name + v.folder).toLowerCase().includes(query));
  const scroll = $('library').scrollTop;
  $('library').innerHTML = '';
  let folder = null;
  for (const video of filtered) {
    if (folder !== video.folder) { const label = document.createElement('div'); label.className = 'folder-label'; label.textContent = video.folder === '.' ? 'Video utama' : video.folder; $('library').append(label); folder = video.folder; }
    const button = document.createElement('button');
    button.className = 'video-item' + (selectedPaths.has(video.path) ? ' selected' : '');
    button.title = video.name;
    button.setAttribute('aria-pressed', selectedPaths.has(video.path));
    button.innerHTML = `<span class="video-symbol">▷</span><span class="video-text"><strong>${escapeHTML(video.name.replace(/^CHP\s+\d+\s+/i,''))}</strong><small>${video.size_mb} MB · ${video.subtitle ? 'Subtitle Inggris tersedia' : 'Transkripsi otomatis'}</small></span><span class="video-select"></span>`;
    button.onclick = () => { if (selectedPaths.has(video.path)) selectedPaths.delete(video.path); else selectedPaths.add(video.path); renderLibrary(); };
    const row = document.createElement('div'); row.className = 'library-video-row'; row.append(button);
    const results = libraryResults[video.path] || [];
    if (results.length) {
      const badge = document.createElement('small'); badge.className = 'dubbed-badge'; badge.textContent = '✓ Sudah dubbing'; button.querySelector('.video-text').append(badge);
      const actions = document.createElement('div'); actions.className = 'library-result-actions';
      results.forEach(result => {
        const group = document.createElement('div'); group.className = 'library-result-group';
        const format = result.mode === 'audio' ? 'MP3' : 'MP4';
        const play = document.createElement('button'); play.className = 'secondary'; play.textContent = `Play ${format} ▶`; play.setAttribute('aria-label', `Play ${format}: ${video.name}`); play.onclick = () => openPreview(video.name, result);
        const download = document.createElement('a'); download.className = 'secondary'; download.textContent = `Download ${format} ↓`; download.href = result.download_url; download.download = ''; download.setAttribute('aria-label', `Download ${format}: ${video.name}`);
        group.append(play, download); actions.append(group);
      });
      row.append(actions);
    }
    $('library').append(row);
  }
  if (!filtered.length) $('library').innerHTML = '<p class="muted">Tidak ada video yang cocok. Anda juga bisa mengunggah video sendiri.</p>';
  updateSelection();
  $('library').scrollTop = scroll;
}
async function refreshLibraryResults() {
  if (!playlistId || loadingCourse || resultRefreshBusy) return;
  const id = playlistId, requestId = courseRequest;
  resultRefreshBusy = true;
  try {
    const results = await api(`playlists/${id}/results`);
    if (id === playlistId && requestId === courseRequest && JSON.stringify(results) !== JSON.stringify(libraryResults)) {
      libraryResults = results; renderLibrary();
    }
  } catch (_) { /* Retain the last known results during temporary disconnections. */ }
  finally { resultRefreshBusy = false; }
}
setInterval(() => {
  if (!document.hidden && !activeId && sourceMode === 'library' && !$('previewDialog').open) refreshLibraryResults();
}, 5000);
function updatePreviewControls() {
  const video = $('previewVideo');
  $('previewToggle').textContent = previewPlayback?.wantsPlay ? 'Pause Ⅱ' : 'Play ▶';
  const duration = Number.isFinite(video.duration) ? video.duration : 0;
  $('previewSeek').disabled = !duration;
  $('previewSeek').max = duration;
  $('previewSeek').value = video.currentTime || 0;
  $('previewTime').textContent = `${timestamp(video.currentTime || 0)} / ${timestamp(duration)}`;
}
function stopPreview() {
  previewPlayback?.dispose(); previewPlayback = null;
  [$('previewVideo'), $('previewAudio')].forEach(media => { media.pause(); media.removeAttribute('src'); media.load(); });
}
function openPreview(title, result) {
  stopPreview(); $('player').pause(); $('audioPlayer').pause();
  const audioOnly = result.mode === 'audio';
  $('previewTitle').textContent = title;
  $('previewNote').textContent = audioOnly ? 'Video asli diputar bersama audio dubbing. Suara asli dibisukan.' : 'Video dengan sulih suara dalam bahasa pilihan.';
  $('previewError').textContent = ''; $('previewError').classList.add('hidden');
  $('previewDownload').href = result.download_url; $('previewDownload').textContent = audioOnly ? 'Download MP3 ↓' : 'Download MP4 ↓';
  $('previewRate').value = '1'; $('previewVolume').value = '1';
  const video = $('previewVideo'), audio = $('previewAudio');
  video.muted = audioOnly; video.volume = 1; audio.volume = 1; audio.muted = false;
  video.playbackRate = 1; audio.playbackRate = 1;
  previewPlayback = new DubbingPlayback(video, audioOnly ? audio : null, updatePreviewControls, message => {
    $('previewError').textContent = message; $('previewError').classList.remove('hidden');
  });
  video.src = audioOnly ? result.source_url : result.media_url;
  if (audioOnly) audio.src = result.media_url;
  if (!$('previewDialog').open) $('previewDialog').showModal();
  previewPlayback.play();
}
$('closePreview').onclick = () => $('previewDialog').close();
$('previewDialog').addEventListener('close', stopPreview);
$('previewDialog').addEventListener('cancel', () => stopPreview());
$('previewToggle').onclick = () => {
  if (!previewPlayback) return;
  $('previewError').classList.add('hidden');
  if (previewPlayback.wantsPlay) previewPlayback.pause(); else previewPlayback.play();
};
$('previewSeek').oninput = () => previewPlayback?.seek(+$('previewSeek').value);
$('previewRate').onchange = () => previewPlayback?.setRate(+$('previewRate').value);
$('previewVolume').oninput = () => previewPlayback?.setVolume(+$('previewVolume').value);
function updateSelection() {
  const count = sourceMode === 'library' ? selectedPaths.size : $('videoFile').files.length;
  $('selectionCount').textContent = `${count} video dipilih`;
  $('batchHint').textContent = count > 1 ? 'Semua video diproses berurutan hingga selesai. Terjemahan bisa diedit setelah hasil tersedia.' : 'Pilih satu atau beberapa video. Untuk satu video, periksa terjemahan sebelum membuat hasil.';
  $('subtitleFile').disabled = count > 1;
}
$('selectAll').onclick = () => { const query = $('search').value.toLowerCase(); library.filter(v => (v.name + v.folder).toLowerCase().includes(query)).forEach(v => selectedPaths.add(v.path)); renderLibrary(); };
$('clearSelection').onclick = () => { selectedPaths.clear(); renderLibrary(); };
document.querySelectorAll('[data-source]').forEach(button => button.onclick = () => switchSource(button.dataset.source));
$('search').oninput = renderLibrary;
$('rate').oninput = () => $('rateValue').textContent = +$('rate').value === 0 ? 'Normal' : `${+$('rate').value > 0 ? '+' : ''}${$('rate').value}%`;
$('tts').onchange = () => {
  const provider = $('tts').value;
  const voices = providerVoices(provider), previous = $('voice').value;
  if (provider !== 'supertonic' && $('language').value !== 'id') $('language').value = 'id';
  $('voice').innerHTML = voices.map(([id,label]) => `<option value="${id}">${label}</option>`).join('');
  $('voice').value = voices.some(([id]) => id === previous) ? previous : voices[0][0];
  $('voiceProvider').textContent = provider === 'supertonic' ? 'Supertonic 3 | CPU | offline' : provider === 'onnx' ? 'Wikidepia ONNX | offline' : provider === 'wikidepia' ? 'Wikidepia lokal (data suara Azure)' : 'Microsoft Neural';
  $('voiceNote').textContent = provider === 'supertonic' ? '10 preset suara dan 30 bahasa. Sintesis berjalan di CPU, tanpa internet dan tanpa API.' : 'Mesin suara ini hanya mendukung bahasa Indonesia.';
  $('language').disabled = provider !== 'supertonic';
};
function providerVoices(provider) {
  return provider === 'supertonic'
    ? ['M1','M2','M3','M4','M5','F1','F2','F3','F4','F5'].map(v => [`supertonic-${v}`, `Supertonic ${v} | ${v[0] === 'M' ? 'Pria' : 'Wanita'}`])
    : [['id-ID-ArdiNeural', 'Ardi - Pria'], ['id-ID-GadisNeural', 'Gadis - Wanita']];
}
function reviewVoices(provider, selected) {
  const voices = providerVoices(provider);
  $('reviewVoice').innerHTML = voices.map(([id, label]) => `<option value="${id}">${label}</option>`).join('');
  $('reviewVoice').value = voices.some(([id]) => id === selected) ? selected : voices[0][0];
}
$('videoFile').onchange = () => { $('uploadName').textContent = [...$('videoFile').files].map(f => f.name).join(', '); updateSelection(); };
['dragover','dragleave','drop'].forEach(event => $('dropzone').addEventListener(event, e => { e.preventDefault(); $('dropzone').classList.toggle('drag', event === 'dragover'); if (event === 'drop' && e.dataTransfer.files.length) { const dt = new DataTransfer(); [...e.dataTransfer.files].forEach(file => dt.items.add(file)); $('videoFile').files = dt.files; $('videoFile').onchange(); } }));
function settings() { return {voice: $('voice').value, language: $('language').value, rate:$('rate').value, original_volume:$('volume').value, tts:$('tts').value, translator:$('translator').value, model:$('model').value}; }
async function startProjects(outputMode) {
  notice('');
  if (importing || loadingCourse) return notice('Tunggu sampai folder selesai dimuat terlebih dahulu.');
  if (sourceMode === 'library' && !selectedPaths.size) return notice('Pilih satu atau beberapa video dari pustaka kursus.');
  if (sourceMode === 'upload' && !$('videoFile').files.length) return notice('Pilih video yang ingin diterjemahkan.');
  const form = new FormData(); Object.entries(settings()).forEach(([k,v]) => form.append(k,v));
  form.append('output_mode', outputMode);
  if (sourceMode === 'library') { form.append('playlist_id', playlistId); selectedPaths.forEach(path => form.append('library_path', path)); }
  else {
    const files = [...$('videoFile').files];
    if (files.some(file => !/\.(mp4|mkv|mov|webm|avi|m4v)$/i.test(file.name))) return notice('Semua file harus berupa video MP4, MKV, MOV, WEBM, AVI, atau M4V.');
    if (files.reduce((total, file) => total + file.size, 0) >= 8 * 1024 ** 3) return notice('Total unggahan harus kurang dari 8 GB. Pilih lebih sedikit video.');
    files.forEach(file => form.append('video', file));
  }
  if (!$('subtitleFile').disabled && $('subtitleFile').files.length) form.append('subtitle', $('subtitleFile').files[0]);
  $('startAudio').disabled = true;
  $('start').disabled = true; $('start').textContent = sourceMode === 'upload' ? 'Mengunggah video…' : 'Menyiapkan video…';
  try { const result = await api('jobs/batch', form); dirty = false; await openProject(result.jobs[0].id); }
  catch (error) { notice(error.message); }
  finally { $('start').disabled = false; $('startAudio').disabled = false; $('start').innerHTML = 'Terjemahkan video <span>→</span>'; }
}
$('start').onclick = () => startProjects('video');
$('startAudio').onclick = () => startProjects('audio');
function timestamp(n) { const sec = Math.floor(n); return `${Math.floor(sec/60).toString().padStart(2,'0')}:${(sec%60).toString().padStart(2,'0')}`; }
function showJob(job) {
  currentJob = job;
  const busy = activeStates.includes(job.status);
  const audioOnly = job.output_mode === 'audio';
  $('render').textContent = audioOnly ? 'Buat audio dubbing →' : 'Buat video dubbing →';
  $('projectTitle').textContent = job.title; $('statusText').textContent = job.message; document.querySelector('#result h2').textContent = `Belajar dalam ${job.language_name || 'Indonesia'}`;
  $('percent').textContent = `${Math.round(job.progress || 0)}%`; $('progressBar').style.width = `${job.progress || 0}%`;
  $('cancel').classList.toggle('hidden', !busy);
  $('retry').classList.toggle('hidden', !['error','cancelled','interrupted'].includes(job.status));
  $('jobError').textContent = job.error || ''; $('jobError').classList.toggle('hidden', !job.error);
  $('step1').classList.remove('current'); $('step2').classList.toggle('current', job.phase !== 'render'); $('step3').classList.toggle('current', job.phase === 'render');
  const editable = job.segments?.length > 0 && !busy;
  $('review').classList.toggle('hidden', !editable);
  if (editable && editorId !== job.id) {
    grammarUndo=null; $('undoGrammar').classList.add('hidden');
    let voiceTools = $('reviewVoiceTools');
    if (!voiceTools) {
      voiceTools = document.createElement('div'); voiceTools.id = 'reviewVoiceTools'; voiceTools.className = 'review-voice-tools';
      voiceTools.innerHTML = '<label>Suara<select id="reviewVoice"><option value="id-ID-ArdiNeural">Ardi</option><option value="id-ID-GadisNeural">Gadis</option></select></label><label>Mesin suara<select id="reviewTts"></select></label>';
      $('segments').parentNode.insertBefore(voiceTools, $('segments').parentNode.querySelector('.editor-toolbar'));
      voiceTools.querySelectorAll('select').forEach(select => select.onchange = () => { dirty = true; $('save').textContent = 'Simpan perubahan'; });
      $('reviewTts').onchange = () => { reviewVoices($('reviewTts').value); dirty = true; $('save').textContent = 'Simpan perubahan'; };
    }
    $('reviewTts').innerHTML = $('tts').innerHTML;
    $('reviewTts').value = job.tts;
    [...$('reviewTts').options].forEach(option=>{option.disabled=(job.language||'id')!=='id'&&option.value!=='supertonic';});
    reviewVoices(job.tts, job.voice);
    $('editorTargetLabel').textContent = `TERJEMAHAN ${String(job.language || 'id').toUpperCase()} | DAPAT DIEDIT`;
    $('segments').innerHTML = job.segments.map((s,i) => `<div class="segment"><time>${timestamp(s.start)}<br>${timestamp(s.end)}</time><p>${escapeHTML(s.en)}</p><div class="segment-output"><textarea aria-label="Terjemahan bagian ${i+1}" data-index="${i}">${escapeHTML(s.id)}</textarea><button class="text-button improve-text" data-index="${i}">Grammar AI</button></div></div>`).join('');
    $('segments').querySelectorAll('.improve-text').forEach(button=>button.onclick=async()=>{const area=$('segments').querySelector(`textarea[data-index="${button.dataset.index}"]`);button.disabled=true;button.textContent='Memproses';try{const result=await api(`jobs/${job.id}/improve/${button.dataset.index}`,{text:area.value});area.value=result.text;dirty=true;$('save').textContent='Simpan perubahan';}catch(error){notice(error.message);}finally{button.disabled=false;button.textContent='Grammar AI';}});
    $('segments').querySelectorAll('textarea').forEach(area => area.oninput = () => { dirty = true; $('save').textContent = 'Simpan perubahan'; });
    $('segmentCount').textContent = `${job.segments.length} bagian · ${timestamp(job.duration)} durasi video`;
    editorId = job.id;
  }
  $('result').classList.toggle('hidden', job.status !== 'done');
  if (job.status === 'done') {
    const base = `/api/jobs/${job.id}/files/`;
    const player = audioOnly ? $('audioPlayer') : $('player');
    const filename = audioOnly ? 'hasil.mp3' : 'hasil.mp4';
    $('player').classList.toggle('hidden', audioOnly); $('audioPlayer').classList.toggle('hidden', !audioOnly);
    if (player.dataset.job !== job.id) {
      player.src = base + filename;
      if (!audioOnly) player.innerHTML = `<track kind="subtitles" src="${base}subtitle.${job.language || 'id'}.vtt" srclang="${job.language || 'id'}" label="${escapeHTML(job.language_name || job.language || 'Indonesia')}" default><track kind="subtitles" src="${base}subtitle.en.vtt" srclang="en" label="English">`;
      player.dataset.job = job.id;
    }
    $('downloadVideo').href = base + filename + '?download=1';
    $('downloadVideo').textContent = audioOnly ? 'Unduh audio MP3 ↓' : 'Unduh video ↓';
    $('resultNote').textContent = audioOnly ? `Audio sulih suara ${job.language_name || 'Indonesia'} dalam format MP3, dengan durasi mengikuti video sumber.` : 'Subtitle dapat dinyalakan melalui tombol CC. Audio Inggris asli juga tersedia sebagai track kedua pada pemutar yang mendukungnya.';
    $('downloads').innerHTML = [[`subtitle.${job.language || 'id'}.srt`,`Subtitle ${job.language_name || 'Indonesia'}`],['subtitle.en.srt','Subtitle Inggris'],['transkrip.txt','Transkrip']].map(([name,label]) => `<a href="${base}${name}?download=1" download>${label} ↓</a>`).join('');
  }
  const warnings = job.warnings || []; $('warnings').classList.toggle('hidden', !warnings.length); $('warnings').textContent = warnings.join('\n');
}
async function poll() {
  if (!activeId) return;
  const id = activeId;
  try { const job = await api(`jobs/${id}`); if (activeId !== id) return; showJob(job); await refreshHistory(); if (activeId === id) timer = setTimeout(poll, activeStates.includes(job.status) ? 1600 : 3500); }
  catch (error) { notice(error.message + ' Mencoba menghubungkan kembali…'); if (activeId === id) timer = setTimeout(poll, 5000); }
}
async function leaveEdits() { if (dirty && activeId) await saveTexts(); }
async function openProject(id) {
  await leaveEdits(); clearTimeout(timer); activeId = id; editorId = null;
  $('player').pause(); $('audioPlayer').pause();
  showWorkspaceView('project'); notice('');
  await poll();
}
async function newProject() {
  try { await leaveEdits(); clearTimeout(timer); activeId = null; $('player').pause(); $('audioPlayer').pause(); showWorkspaceView('setup'); $('step1').classList.add('current'); $('step2').classList.remove('current'); $('step3').classList.remove('current'); notice(''); await refreshLibraryResults(); }
  catch (error) { notice(error.message); }
}

const jobStatusLabels = {queued:'Menunggu', preparing:'Menerjemahkan', rendering:'Membuat hasil', review:'Siap diperiksa', done:'Selesai', error:'Gagal', cancelled:'Dibatalkan', interrupted:'Terputus'};
function showWorkspaceView(view) {
  for (const id of ['setup','project','historyPage','playlistPage']) $(id).classList.toggle('hidden', id !== view);
  document.querySelectorAll('.eyebrow, .page>h1, .intro, .steps').forEach(element => element.classList.toggle('hidden', ['historyPage','playlistPage'].includes(view)));
  $('newProject').classList.toggle('active', view === 'setup' || view === 'project');
  $('showHistory').classList.toggle('active', view === 'historyPage');
  $('showPlaylists').classList.toggle('active', view === 'playlistPage');
  document.querySelector('.breadcrumb strong').textContent = view === 'historyPage' ? 'History' : view === 'playlistPage' ? 'Playlist video' : 'Studio video';
}
function showSavedKey(configured) {
  const input=$('openrouterKey');
  input.readOnly=Boolean(configured);
  input.value=configured?'***************':'';
  input.placeholder=configured?'API key tersimpan':'Masukkan API key OpenRouter';
  $('changeOpenrouterKey').classList.toggle('hidden',!configured);
  $('openrouterKeyStatus').textContent=configured?'API key sudah tersimpan. Tanda bintang mewakili key Anda. Gunakan Ganti API key untuk menggantinya.':'Belum ada API key tersimpan.';
}
$('changeOpenrouterKey').onclick=()=>{ $('openrouterKey').readOnly=false; $('openrouterKey').value=''; $('openrouterKey').focus(); $('openrouterKeyStatus').textContent='Masukkan key baru, lalu Simpan. Kolom kosong tetap memakai key lama.'; };
async function showHistoryPage() {
  await leaveEdits(); clearTimeout(timer); activeId=null;
  $('player').pause(); $('audioPlayer').pause();
  showWorkspaceView('historyPage'); notice('');
  await renderHistoryPage();
}
async function renderHistoryPage() {
  const requestId=++historyLoad;
  const result=await api(`history?page=${historyPageNumber}&page_size=${$('historyPageSize').value}`);
  if(requestId!==historyLoad)return;
  historyPageNumber=result.page;
  $('historyTotal').textContent=`${result.total} proyek tersimpan`;
  $('historyPageLabel').textContent=`Halaman ${result.page} dari ${result.pages}`;
  $('historyPrev').disabled=result.page<=1; $('historyNext').disabled=result.page>=result.pages;
  historyVisible=result.items;
  $('history').replaceChildren();
  if(!result.items.length){const row=$('history').insertRow();const cell=row.insertCell();cell.colSpan=6;cell.textContent='Belum ada proyek.';}
  for(const job of result.items){
    if(historySelected.has(job.id))historySelected.set(job.id,job);
    const row=$('history').insertRow();row.className='history-entry';
    const check=document.createElement('input');check.type='checkbox';check.dataset.job=job.id;
    check.setAttribute('aria-label',`Pilih ${job.title}`);check.disabled=activeStates.includes(job.status);check.checked=historySelected.has(job.id);
    check.onchange=()=>{if(check.checked)historySelected.set(job.id,job);else historySelected.delete(job.id);updateHistorySelection();};row.insertCell().append(check);
    row.insertCell().textContent=job.title;
    row.insertCell().textContent=jobStatusLabels[job.status]||job.status;
    row.insertCell().textContent=job.language_name||'Indonesia';row.insertCell().textContent=job.output_mode==='audio'?'MP3':'MP4';
    const actions=row.insertCell();actions.className='table-actions';
    actions.append(actionButton('Play',()=>playHistory(job),!canPlay(job)));
    const open=actionButton('Buka / Edit',()=>openProject(job.id));open.classList.add('history-open');actions.append(open);
    if(job.media){const link=document.createElement('a');link.className='secondary';link.textContent='Unduh';link.href=job.media.download_url;link.setAttribute('download','');actions.append(link);}
    const remove=actionButton('Hapus',async()=>{if(!confirm(`Hapus proyek "${job.title}" beserta seluruh hasilnya?`))return;await api(`jobs/${job.id}`,{method:'DELETE'});historySelected.delete(job.id);await renderHistoryPage();},activeStates.includes(job.status));remove.classList.add('text-button');actions.append(remove);
  }
  updateHistorySelection();
}
function actionButton(label,action,disabled=false){
  const button=document.createElement('button');button.className='secondary';button.textContent=label;button.disabled=disabled;
  button.onclick=async()=>{button.disabled=true;try{await action();}catch(error){notice(error.message);}finally{button.disabled=disabled;}};return button;
}
function canPlay(job){return Boolean(job.media && (job.media.mode!=='audio'||job.media.source_available));}
function updateHistorySelection(){
  const chosen=[...historySelected.values()], eligible=historyVisible.filter(job=>!activeStates.includes(job.status));
  $('historySelection').textContent=`${chosen.length} dipilih (termasuk halaman lain)`;
  $('historyDelete').disabled=!chosen.length;
  $('historyPlaylist').disabled=!chosen.length || chosen.some(job=>!job.media);
  const count=eligible.filter(job=>historySelected.has(job.id)).length;
  $('historySelectPage').checked=eligible.length>0 && count===eligible.length;
  $('historySelectPage').indeterminate=count>0 && count<eligible.length;$('historySelectPage').disabled=!eligible.length;
}
$('historySelectPage').onchange=()=>{for(const job of historyVisible.filter(job=>!activeStates.includes(job.status))){if($('historySelectPage').checked)historySelected.set(job.id,job);else historySelected.delete(job.id);}for(const input of $('history').querySelectorAll('input'))input.checked=historySelected.has(input.dataset.job);updateHistorySelection();};
$('historyClear').onclick=()=>{historySelected.clear();for(const input of $('history').querySelectorAll('input'))input.checked=false;updateHistorySelection();};
$('historyDelete').onclick=async()=>{
  const ids=[...historySelected.keys()];if(!ids.length || !confirm(`Hapus ${ids.length} proyek terpilih beserta file hasilnya secara permanen? Tindakan ini tidak dapat diurungkan.`))return;
  $('historyDelete').disabled=true;let removed=0;const errors=[];
  for(const id of ids){try{await api(`jobs/${id}`,{method:'DELETE'});historySelected.delete(id);removed++;}catch(error){errors.push(error.message);}}
  await renderHistoryPage();notice(`${removed} proyek dihapus.${errors.length?` ${errors.length} gagal: ${errors[0]}`:''}`);
};
function playHistory(job){watchQueue=[];$('watchTransport').classList.add('hidden');openPreview(job.title,job.media);}
async function showPlaylistPage(){
  await leaveEdits();clearTimeout(timer);activeId=null;$('player').pause();$('audioPlayer').pause();
  showWorkspaceView('playlistPage');notice('');await refreshWatchlists();
}
async function refreshWatchlists(){
  watchLists=await api('watch-playlists');$('watchPlaylists').replaceChildren();
  if(!watchLists.some(item=>item.id===watchId))watchId=watchLists[0]?.id||null;
  if(!watchLists.length)$('watchPlaylists').textContent='Belum ada playlist. Pilih hasil selesai di History, lalu Tambahkan ke playlist.';
  for(const item of watchLists){const button=actionButton(`${item.name} (${item.items.length})`,()=>{watchId=item.id;renderWatchDetails();});button.setAttribute('aria-pressed',item.id===watchId);$('watchPlaylists').append(button);}
  renderWatchDetails();
}
function renderWatchDetails(){
  $('watchDetails').replaceChildren();const list=watchLists.find(item=>item.id===watchId);if(!list)return;
  for(const [i,button] of [...$('watchPlaylists').children].entries())button.setAttribute('aria-pressed',watchLists[i]?.id===watchId);
  const title=document.createElement('h3');title.textContent=list.name;$('watchDetails').append(title);
  const actions=document.createElement('div');actions.className='selection-actions';
  actions.append(actionButton('Play semua',()=>startWatch(list.items),!list.items.some(canPlay)),actionButton('Ganti nama',async()=>{const name=prompt('Nama playlist',list.name);if(name===null)return;await api(`watch-playlists/${list.id}`,{name});await refreshWatchlists();}),actionButton('Hapus playlist',async()=>{if(!confirm(`Hapus playlist "${list.name}"? Proyek dan hasil di History tetap disimpan.`))return;await api(`watch-playlists/${list.id}`,{method:'DELETE'});await refreshWatchlists();}));
  const downloads=list.items.filter(job=>job.media);
  if(downloads.length){const download=document.createElement('a');download.className='secondary';download.textContent=`Unduh semua (${downloads.length} hasil, ZIP)`;download.href=`/api/watch-playlists/${list.id}/download`;download.setAttribute('download','');actions.append(download);}
  const downloadNote=document.createElement('p');downloadNote.className='muted';downloadNote.textContent='Unduh semua membuat satu ZIP berisi hasil MP4/MP3 yang tersedia. Hasil yang belum selesai atau telah dihapus dilewati.';
  $('watchDetails').append(actions,downloadNote);
  const wrap=document.createElement('div');wrap.className='table-scroll';const table=document.createElement('table');table.className='data-table';
  table.innerHTML='<thead><tr><th>No.</th><th>Proyek</th><th>Status</th><th>Tindakan</th></tr></thead><tbody></tbody>';
  const body=table.querySelector('tbody');
  list.items.forEach((job,index)=>{const row=body.insertRow();row.insertCell().textContent=index+1;row.insertCell().textContent=job.title;row.insertCell().textContent=canPlay(job)?'Siap diputar':job.media?'Video sumber tidak tersedia':jobStatusLabels[job.status]||'Tidak tersedia';const cell=row.insertCell();cell.className='table-actions';cell.append(actionButton('Play',()=>startWatch(list.items,job.id),!canPlay(job)),actionButton('Buka / Edit',()=>openProject(job.id),job.status==='missing'),actionButton('Keluarkan',async()=>{await api(`watch-playlists/${list.id}`,{remove_ids:[job.id]});await refreshWatchlists();}));if(job.media){const link=document.createElement('a');link.className='secondary';link.textContent='Unduh';link.href=job.media.download_url;link.setAttribute('download','');cell.append(link);}});
  wrap.append(table);$('watchDetails').append(wrap);
}
function startWatch(items,id){watchQueue=items.filter(canPlay);watchIndex=Math.max(0,watchQueue.findIndex(job=>job.id===id));playWatch();}
function playWatch(){const job=watchQueue[watchIndex];if(!job)return;openPreview(job.title,job.media);$('watchTransport').classList.remove('hidden');$('watchPrevious').disabled=watchIndex===0;$('watchNext').disabled=watchIndex===watchQueue.length-1;$('watchPosition').textContent=`${watchIndex+1} / ${watchQueue.length}`;}
$('watchPrevious').onclick=()=>{if(watchIndex>0){watchIndex--;playWatch();}};
$('watchNext').onclick=()=>{if(watchIndex<watchQueue.length-1){watchIndex++;playWatch();}};
$('previewVideo').addEventListener('ended',()=>{if($('previewDialog').open && watchQueue.length && watchIndex<watchQueue.length-1){queueMicrotask(()=>{$('watchNext').onclick();});}});
$('previewDialog').addEventListener('close',()=>{watchQueue=[];$('watchTransport').classList.add('hidden');});
$('playlistFromHistory').onclick=()=>showHistoryPage().catch(error=>notice(error.message));
$('historyPlaylist').onclick=async()=>{try{watchLists=await api('watch-playlists');$('watchTarget').replaceChildren(new Option('Buat playlist baru',''));for(const list of watchLists)$('watchTarget').add(new Option(list.name,list.id));$('watchName').value='';$('watchName').disabled=false;$('watchCreateStatus').textContent=`${historySelected.size} hasil dipilih`;$('watchCreateDialog').showModal();}catch(error){notice(error.message);}};
$('watchTarget').onchange=()=>{$('watchName').disabled=Boolean($('watchTarget').value);};
$('watchCreateCancel').onclick=()=>$('watchCreateDialog').close();
$('watchCreateSave').onclick=async()=>{
  $('watchCreateSave').disabled=true;
  try{const target=$('watchTarget').value;const payload={job_ids:[...historySelected.keys()]};if(!target)payload.name=$('watchName').value;
    const list=await api(`watch-playlists${target?'/'+target:''}`,payload);watchId=list.id;$('watchCreateDialog').close();historySelected.clear();await showPlaylistPage();
  }catch(error){$('watchCreateStatus').textContent=error.message;}finally{$('watchCreateSave').disabled=false;}
};
$('historyPrev').onclick=async()=>{historyPageNumber=Math.max(1,historyPageNumber-1);try{await renderHistoryPage();}catch(error){notice(error.message);}};
$('historyNext').onclick=async()=>{historyPageNumber++;try{await renderHistoryPage();}catch(error){notice(error.message);}};
$('historyPageSize').onchange=async()=>{historyPageNumber=1;try{await renderHistoryPage();}catch(error){notice(error.message);}};

async function openAiSettings() {
  const dialog=$('settingsDialog'); $('settingsStatus').textContent='Memuat pilihan model gratis?';
  try {
    const [settings, models]=await Promise.all([api('settings'),api('openrouter/models')]);
    $('openrouterModel').innerHTML=models.map(model=>`<option value="${escapeHTML(model.id)}">${escapeHTML(model.name)}</option>`).join('');
    if (!models.some(model=>model.id===settings.openrouter_model)) $('openrouterModel').insertAdjacentHTML('beforeend',`<option value="${escapeHTML(settings.openrouter_model)}">${escapeHTML(settings.openrouter_model)}</option>`);
    $('openrouterModel').value=settings.openrouter_model;
    showSavedKey(settings.openrouter_configured);
    $('settingsStatus').textContent='Pilih router otomatis atau model gratis yang tersedia.';
    dialog.showModal();
  } catch(error) {$('settingsStatus').textContent=error.message;dialog.showModal();}
}
$('openSettings').onclick=openAiSettings;
$('openRouterSettings').onclick=openAiSettings;
$('saveAiSettings').onclick=async()=>{const button=$('saveAiSettings');button.disabled=true;try{const result=await api('settings',{openrouter_key:$('openrouterKey').readOnly?'':$('openrouterKey').value,openrouter_model:$('openrouterModel').value});showSavedKey(result.openrouter_configured);$('settingsStatus').textContent='Pengaturan tersimpan di komputer ini.';}catch(error){$('settingsStatus').textContent=error.message;}finally{button.disabled=false;}};
$('showHistory').onclick=()=>showHistoryPage().catch(error=>notice(error.message));
$('showPlaylists').onclick=()=>showPlaylistPage().catch(error=>notice(error.message));
$('back').onclick = newProject; $('newProject').onclick = newProject;
async function refreshHistory() {
  if (!currentJob?.batch_id || currentJob.id !== activeId) { $('batchQueue').classList.add('hidden'); return; }
  const projects = await api('jobs');
  const labels = jobStatusLabels;
  const batch = currentJob?.id === activeId && currentJob.batch_id ? projects.filter(job => job.batch_id === currentJob.batch_id).reverse() : [];
  $('batchQueue').classList.toggle('hidden', !batch.length);
  $('batchSummary').textContent = `${batch.filter(job => job.status === 'done').length}/${batch.length} video selesai`;
  $('batchJobs').innerHTML = '';
  batch.forEach(job => {
    const row = document.createElement('div'); row.className = 'batch-row';
    const button = document.createElement('button'); button.className = 'secondary'; button.textContent = `${job.title} · ${labels[job.status] || job.status}`; button.setAttribute('aria-current', job.id === activeId ? 'true' : 'false'); button.onclick = () => openProject(job.id).catch(e => notice(e.message)); row.append(button);
    if (job.status === 'done') { const link = document.createElement('a'); link.textContent = job.output_mode === 'audio' ? 'Unduh MP3 ↓' : 'Unduh video ↓'; link.href = `/api/jobs/${job.id}/files/hasil.${job.output_mode === 'audio' ? 'mp3' : 'mp4'}?download=1`; link.setAttribute('download', ''); row.append(link); }
    $('batchJobs').append(row);
  });
}
async function saveTexts() {
  const texts = [...$('segments').querySelectorAll('textarea')].map(t => t.value);
  const job = await api(`jobs/${activeId}/save`, {translations:texts, voice:$('reviewVoice').value, tts:$('reviewTts').value});
  dirty = false; $('save').textContent = 'Tersimpan ✓'; return job;
}
$('save').onclick = async () => { try { $('save').disabled = true; const job = await saveTexts(); showJob(job); } catch(e) { notice(e.message); } finally { $('save').disabled = false; } };
$('render').onclick = async () => {
  try { $('render').disabled = true; notice(''); await saveTexts(); const job = await api(`jobs/${activeId}/render`, {}); [$('player'), $('audioPlayer')].forEach(player => { player.pause(); player.removeAttribute('data-job'); }); showJob(job); clearTimeout(timer); timer = setTimeout(poll, 1000); }
  catch(e) { notice(e.message); } finally { $('render').disabled = false; }
};
$('retry').onclick = async () => { try { if(dirty) await saveTexts(); await api(`jobs/${activeId}/retry`, {}); clearTimeout(timer); await poll(); } catch(e) { notice(e.message); } };
$('cancel').onclick = async () => { try { await api(`jobs/${activeId}/cancel`, {}); } catch(e) { notice(e.message); } };
window.addEventListener('beforeunload', e => { if (dirty || importing) { e.preventDefault(); e.returnValue = ''; } });
let grammarRun=null, grammarUndo=null;
const grammarAreas=()=>[...$('segments').querySelectorAll('textarea')];
function cancelGrammar() {
  if(grammarRun) grammarRun.controller.abort();
  grammarRun=null; $('grammarAll').disabled=false; $('applyGrammar').disabled=true;
}
$('cancelGrammar').onclick=()=>{cancelGrammar();$('grammarDialog').close();};
$('grammarDialog').addEventListener('cancel',cancelGrammar);
$('grammarDialog').addEventListener('close',cancelGrammar);
$('grammarAll').onclick=async()=>{
  const originals=grammarAreas().map(area=>area.value);
  if(!activeId || !originals.length) return;
  if(originals.some(text=>!text.trim() || text.length>4000)){notice('Isi setiap bagian dengan 1 sampai 4000 karakter.');return;}
  cancelGrammar();
  const run={jobId:activeId, originals, results:[], controller:new AbortController()};
  grammarRun=run; $('grammarAll').disabled=true; $('grammarPreview').replaceChildren();
  $('grammarStatus').textContent='Memproses grammar seluruh bagian...';
  $('grammarProgress').max=originals.length; $('grammarProgress').value=0;
  $('grammarDialog').showModal();
  try {
    let offset=0;
    while(offset<originals.length){
      const items=[]; let size=0;
      while(offset<originals.length && items.length<8 && size+originals[offset].length<=8000){
        items.push({index:offset,text:originals[offset]}); size+=originals[offset].length; offset++;
      }
      const result=await api(`jobs/${run.jobId}/grammar`,{items},run.controller.signal);
      if(grammarRun!==run)return;
      if(!Array.isArray(result.items) || result.items.length!==items.length || result.items.some((item,i)=>item.index!==items[i].index || typeof item.text!=='string' || !item.text.trim())) throw new Error('Jawaban AI tidak valid. Teks asli tetap utuh.');
      run.results.push(...result.items);
      $('grammarProgress').value=offset;
      $('grammarStatus').textContent=`Memeriksa ${offset}/${originals.length} bagian...`;
    }
    let changes=0, warnings=0;
    for(const item of run.results){
      const before=originals[item.index];
      if(before===item.text && !item.warning)continue;
      if(before!==item.text)changes++;
      if(item.warning)warnings++;
      const row=document.createElement('section'); row.className='grammar-change';
      const title=document.createElement('strong');title.textContent=`Bagian ${item.index+1}`;
      const oldText=document.createElement('p');oldText.textContent=`Sebelum: ${before}`;
      const newText=document.createElement('p');newText.textContent=`Usulan: ${item.text}`;
      row.append(title,oldText,newText);
      if(item.warning){const warning=document.createElement('p');warning.className='muted';warning.textContent=item.warning;row.append(warning);}
      $('grammarPreview').append(row);
    }
    $('grammarStatus').textContent=`Selesai: ${changes} bagian diusulkan berubah, ${warnings} usulan ditolak otomatis. Tinjau sebelum menerapkan. Teks belum disimpan.`;
    $('applyGrammar').disabled=changes===0;
  } catch(error){
    if(grammarRun!==run)return;
    $('grammarStatus').textContent=`${error.message} Tidak ada perubahan yang diterapkan.`;
    $('applyGrammar').disabled=true;
  }
};
$('applyGrammar').onclick=()=>{
  const run=grammarRun, areas=grammarAreas();
  if(!run || run.results.length!==run.originals.length)return;
  if(activeId!==run.jobId || areas.length!==run.originals.length || areas.some((area,i)=>area.value!==run.originals[i])){
    $('grammarStatus').textContent='Editor berubah selama pemrosesan. Batalkan dan jalankan ulang agar edit Anda tetap utuh.'; $('applyGrammar').disabled=true;return;
  }
  const after=run.results.map(item=>item.text);
  grammarUndo={jobId:run.jobId,before:run.originals,after};
  areas.forEach((area,i)=>{area.value=after[i];});
  dirty=true; $('save').textContent='Simpan perubahan'; $('undoGrammar').classList.remove('hidden');
  cancelGrammar(); $('grammarDialog').close();
};
$('undoGrammar').onclick=()=>{
  const undo=grammarUndo, areas=grammarAreas();
  if(!undo || activeId!==undo.jobId || areas.length!==undo.after.length || areas.some((area,i)=>area.value!==undo.after[i])){notice('Teks sudah diedit lagi. Urungkan grammar tidak diterapkan agar edit terbaru tetap utuh.');return;}
  areas.forEach((area,i)=>{area.value=undo.before[i];});
  dirty=true; $('save').textContent='Simpan perubahan';grammarUndo=null;$('undoGrammar').classList.add('hidden');
};
(async () => {
  try { const [, info] = await Promise.all([refreshPlaylists(),api('info')]);
    let previous; try { previous = localStorage.getItem('dubbing-playlist'); } catch (_) {}
    await loadCourse(playlists.find(c => c.id === previous && c.status === 'ready')?.id || 'default'); await refreshHistory();
    if (!info.ffmpeg) notice('FFmpeg belum tersedia. Pasang FFmpeg dan tambahkan folder bin ke PATH sebelum memproses video.');
    $('tts').querySelector('[value=azure]').disabled = !info.azure_speech; $('translator').querySelector('[value=azure]').disabled = !info.azure_translator;
    $('tts').querySelector('[value=wikidepia]').disabled = !info.wikidepia;
    $('tts').querySelector('[value=onnx]').disabled = !info.onnx;
    $('tts').querySelector('[value=supertonic]').disabled = !info.supertonic;
    $('tts').value = info.default_tts || 'edge';
    $('language').innerHTML = Object.entries(info.languages).map(([code,name]) => `<option value="${code}">${name}</option>`).join('');
    $('language').value = info.default_language || 'id';
    $('language').onchange = () => { const name=$('language').selectedOptions[0]?.textContent || 'ID'; document.querySelector('header .badge').innerHTML=`EN <span>→</span> ${escapeHTML($('language').value.toUpperCase())}`; };
    $('tts').onchange();
  } catch(e) { notice(e.message); }
})();
