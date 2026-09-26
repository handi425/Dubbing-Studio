const $ = id => document.getElementById(id);
let library = [], selectedPaths = new Set(), sourceMode = 'library', activeId = null, currentJob = null, dirty = false, timer = null, editorId = null;
let playlists = [], playlistId = null, loadingCourse = false, importing = false, stopImport = false, resumeCourse = null, courseRequest = 0;
let libraryResults = {}, resultRefreshBusy = false, previewPlayback = null;
const activeStates = ['queued', 'preparing', 'rendering'];
const escapeHTML = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message) { $('notice').textContent = message; $('notice').classList.toggle('hidden', !message); }
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'X-Dubbing-Studio':'1'}};
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
    $('playlists').append(button);
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
  $('previewNote').textContent = audioOnly ? 'Video asli diputar bersama audio Indonesia. Play, pause, posisi, dan kecepatan mengendalikan keduanya; suara asli dibisukan.' : 'Video dengan sulih suara Indonesia.';
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
document.querySelectorAll('[name=voice]').forEach(input => input.onchange = () => document.querySelectorAll('.voice-choice').forEach(label => label.classList.toggle('selected', label.querySelector('input').checked)));
$('rate').oninput = () => $('rateValue').textContent = +$('rate').value === 0 ? 'Normal' : `${+$('rate').value > 0 ? '+' : ''}${$('rate').value}%`;
$('tts').onchange = () => $('voiceProvider').textContent = $('tts').value === 'wikidepia' ? 'Bahasa Indonesia · Wikidepia lokal (data suara Azure)' : 'Bahasa Indonesia · Microsoft Neural';
$('videoFile').onchange = () => { $('uploadName').textContent = [...$('videoFile').files].map(f => f.name).join(', '); updateSelection(); };
['dragover','dragleave','drop'].forEach(event => $('dropzone').addEventListener(event, e => { e.preventDefault(); $('dropzone').classList.toggle('drag', event === 'dragover'); if (event === 'drop' && e.dataTransfer.files.length) { const dt = new DataTransfer(); [...e.dataTransfer.files].forEach(file => dt.items.add(file)); $('videoFile').files = dt.files; $('videoFile').onchange(); } }));
function settings() { return {voice: document.querySelector('[name=voice]:checked').value, rate:$('rate').value, original_volume:$('volume').value, tts:$('tts').value, translator:$('translator').value, model:$('model').value}; }
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
    const player = audioOnly ? $('audioPlayer') : $('player');
    const filename = audioOnly ? 'hasil.mp3' : 'hasil.mp4';
    $('player').classList.toggle('hidden', audioOnly); $('audioPlayer').classList.toggle('hidden', !audioOnly);
    if (player.dataset.job !== job.id) {
      player.src = base + filename;
      if (!audioOnly) player.innerHTML = `<track kind="subtitles" src="${base}subtitle.id.vtt" srclang="id" label="Indonesia" default><track kind="subtitles" src="${base}subtitle.en.vtt" srclang="en" label="English">`;
      player.dataset.job = job.id;
    }
    $('downloadVideo').href = base + filename + '?download=1';
    $('downloadVideo').textContent = audioOnly ? 'Unduh audio MP3 ↓' : 'Unduh video ↓';
    $('resultNote').textContent = audioOnly ? 'Audio sulih suara Indonesia dalam format MP3, dengan durasi mengikuti video sumber.' : 'Subtitle dapat dinyalakan melalui tombol CC. Audio Inggris asli juga tersedia sebagai track kedua pada pemutar yang mendukungnya.';
    $('downloads').innerHTML = [['subtitle.id.srt','Subtitle Indonesia'],['subtitle.en.srt','Subtitle Inggris'],['transkrip.txt','Transkrip bilingual']].map(([name,label]) => `<a href="${base}${name}?download=1" download>${label} ↓</a>`).join('');
  }
  const warnings = job.warnings || []; $('warnings').classList.toggle('hidden', !warnings.length); $('warnings').textContent = warnings.join('\n');
}
async function poll() {
  if (!activeId) return;
  const id = activeId;
  try { const job = await api(`jobs/${id}`); if (activeId !== id) return; showJob(job); await history(); if (activeId === id) timer = setTimeout(poll, activeStates.includes(job.status) ? 1600 : 3500); }
  catch (error) { notice(error.message + ' Mencoba menghubungkan kembali…'); if (activeId === id) timer = setTimeout(poll, 5000); }
}
async function leaveEdits() { if (dirty && activeId) await saveTexts(); }
async function openProject(id) {
  await leaveEdits(); clearTimeout(timer); activeId = id; editorId = null;
  $('player').pause(); $('audioPlayer').pause();
  $('setup').classList.add('hidden'); $('project').classList.remove('hidden'); notice('');
  await poll();
}
async function newProject() {
  try { await leaveEdits(); clearTimeout(timer); activeId = null; $('player').pause(); $('audioPlayer').pause(); $('setup').classList.remove('hidden'); $('project').classList.add('hidden'); $('step1').classList.add('current'); $('step2').classList.remove('current'); $('step3').classList.remove('current'); notice(''); await refreshLibraryResults(); }
  catch (error) { notice(error.message); }
}
$('back').onclick = newProject; $('newProject').onclick = newProject;
async function history() {
  const projects = await api('jobs'); $('history').innerHTML = '';
  if (!projects.length) $('history').innerHTML = '<p class="muted">Proyek Anda akan muncul di sini.</p>';
  const labels = {queued:'Menunggu', preparing:'Menerjemahkan', rendering:'Membuat hasil', review:'Siap diperiksa', done:'Selesai', error:'Gagal', cancelled:'Dibatalkan', interrupted:'Terputus'};
  projects.forEach(job => { const button = document.createElement('button'); button.textContent = `${labels[job.status] || job.status} · ${job.output_mode === 'audio' ? 'MP3' : 'Video'} · ${job.title}`; button.title = button.textContent; button.onclick = () => openProject(job.id).catch(e => notice(e.message)); $('history').append(button); });
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
(async () => {
  try { const [, info] = await Promise.all([refreshPlaylists(),api('info')]);
    let previous; try { previous = localStorage.getItem('dubbing-playlist'); } catch (_) {}
    await loadCourse(playlists.find(c => c.id === previous && c.status === 'ready')?.id || 'default'); await history();
    if (!info.ffmpeg) notice('FFmpeg belum tersedia. Pasang FFmpeg dan tambahkan folder bin ke PATH sebelum memproses video.');
    $('tts').querySelector('[value=azure]').disabled = !info.azure_speech; $('translator').querySelector('[value=azure]').disabled = !info.azure_translator;
    $('tts').querySelector('[value=wikidepia]').disabled = !info.wikidepia;
  } catch(e) { notice(e.message); }
})();
