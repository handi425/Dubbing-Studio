/* One transport for a dubbed MP4, or an original video plus a separate MP3. */
class DubbingPlayback {
  constructor(video, audio, onChange = () => {}, onError = () => {}) {
    this.video = video;
    this.audio = audio;
    this.media = audio ? [video, audio] : [video];
    this.onChange = onChange;
    this.onError = onError;
    this.wantsPlay = false;
    this.disposed = false;
    this.starting = false;
    this.listeners = [];
    if (audio) video.muted = true;
    const listen = (target, event, fn) => {
      target.addEventListener(event, fn);
      this.listeners.push(() => target.removeEventListener(event, fn));
    };
    for (const media of this.media) {
      for (const event of ['loadedmetadata', 'canplay', 'seeked']) listen(media, event, () => this.resume());
      for (const event of ['waiting', 'seeking']) listen(media, event, () => {
        this.hold();
        this.onChange();
      });
      listen(media, 'error', () => {
        this.pause();
        this.onError(media === audio ? 'Audio dubbing gagal dimuat. Hasil mungkin telah diubah; muat ulang playlist.' :
          'Video gagal dimuat. Pastikan file sumber tersedia dan format/codec video didukung browser. Hasil dubbing tetap bisa diunduh.');
      });
    }
    listen(video, 'ended', () => this.pause());
    listen(video, 'timeupdate', () => this.tick());
    listen(video, 'ratechange', () => { if (audio) audio.playbackRate = video.playbackRate; });
    listen(video, 'volumechange', () => { if (audio && !video.muted) video.muted = true; });
    this.interval = setInterval(() => this.tick(), 250);
  }
  hold() { this.media.forEach(media => media.pause()); }
  play() {
    if (this.disposed) return;
    this.wantsPlay = true;
    if (this.video.ended) this.seek(0);
    this.resume();
  }
  pause() {
    this.wantsPlay = false;
    this.hold();
    this.onChange();
  }
  async resume() {
    this.onChange();
    if (this.disposed || !this.wantsPlay || this.starting) return;
    if (this.media.some(media => media.readyState < 3 || media.seeking)) { this.hold(); return; }
    if (this.audio && Math.abs(this.audio.currentTime - this.video.currentTime) > 0.25) {
      this.audio.currentTime = this.video.currentTime;
      if (this.audio.seeking) return;
    }
    this.starting = true;
    try {
      await Promise.all(this.media.map(media => media.play()));
      if (!this.disposed && !this.wantsPlay) this.hold();
    } catch (error) {
      if (this.disposed) return;
      this.hold();
      if (!this.disposed && this.wantsPlay && error.name !== 'AbortError') {
        this.wantsPlay = false;
        this.onError('Pemutaran belum dimulai. Klik Play untuk mencoba kembali.');
      }
    } finally {
      this.starting = false;
      if (!this.disposed) this.onChange();
    }
  }
  seek(time) {
    if (this.disposed || !Number.isFinite(this.video.duration)) return;
    const target = Math.max(0, Math.min(time, this.video.duration));
    this.hold();
    this.media.forEach(media => { if (media.readyState >= 1) media.currentTime = target; });
    this.resume();
  }
  setRate(rate) { this.media.forEach(media => { media.playbackRate = rate; }); }
  setVolume(volume) { (this.audio || this.video).volume = volume; }
  tick() {
    if (this.disposed) return;
    if (this.wantsPlay && !this.starting) {
      if (this.media.some(media => media.readyState < 3 || media.seeking)) this.hold();
      else if (this.media.some(media => media.paused) ||
               (this.audio && Math.abs(this.audio.currentTime - this.video.currentTime) > 0.25)) this.resume();
    }
    this.onChange();
  }
  dispose() {
    this.disposed = true;
    this.wantsPlay = false;
    clearInterval(this.interval);
    this.listeners.forEach(remove => remove());
    this.hold();
  }
}
if (typeof module !== 'undefined') module.exports = DubbingPlayback;
