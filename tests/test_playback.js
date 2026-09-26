const {test} = require('node:test');
const assert = require('node:assert/strict');
const DubbingPlayback = require('../static/playback.js');

class Media extends EventTarget {
  constructor() {
    super(); Object.assign(this, {paused:true, currentTime:0, duration:30, readyState:4, seeking:false, ended:false, playbackRate:1, volume:1, muted:false});
  }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  emit(type) { this.dispatchEvent(new Event(type)); }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup(t, paired = true) {
  const video = new Media(), audio = paired ? new Media() : null, errors = [];
  const player = new DubbingPlayback(video, audio, () => {}, error => errors.push(error));
  t.after(() => player.dispose());
  return {video, audio, player, errors};
}
test('paired playback starts and pauses together, keeping original sound muted', async t => {
  const {video, audio, player} = setup(t);
  player.play(); await flush();
  assert.equal(video.paused, false); assert.equal(audio.paused, false); assert.equal(video.muted, true);
  video.muted = false; video.emit('volumechange'); assert.equal(video.muted, true);
  player.pause(); assert.equal(video.paused, true); assert.equal(audio.paused, true);
  player.tick(); await flush(); assert.equal(video.paused, true);
});
test('seek, speed and volume apply to the paired transport', async t => {
  const {video, audio, player} = setup(t);
  player.seek(12); assert.equal(video.currentTime, 12); assert.equal(audio.currentTime, 12);
  assert.equal(video.paused, true);
  player.setRate(1.5); assert.equal(video.playbackRate, 1.5); assert.equal(audio.playbackRate, 1.5);
  player.setVolume(0.4); assert.equal(audio.volume, 0.4); assert.equal(video.muted, true);
  player.play(); await flush(); player.seek(20); await flush();
  assert.equal(audio.currentTime, 20); assert.equal(video.paused, false); assert.equal(audio.paused, false);
});
test('buffering either stream pauses both and recovers after canplay', async t => {
  const {video, audio, player} = setup(t);
  player.play(); await flush();
  audio.readyState = 2; audio.emit('waiting');
  assert.equal(video.paused, true); assert.equal(audio.paused, true); assert.equal(player.wantsPlay, true);
  audio.readyState = 4; audio.emit('canplay'); await flush();
  assert.equal(video.paused, false); assert.equal(audio.paused, false);
  video.currentTime = 18; audio.currentTime = 16; player.tick(); await flush();
  assert.equal(audio.currentTime, 18);
});
test('metadata arriving late starts both at the current video position', async t => {
  const {video, audio, player} = setup(t);
  audio.readyState = 0; video.currentTime = 10;
  player.play(); await flush(); assert.equal(video.paused, true);
  audio.readyState = 4; audio.emit('canplay'); await flush();
  assert.equal(audio.currentTime, 10); assert.equal(audio.paused, false);
});
test('errors, video ending and popup disposal stop both streams', async t => {
  const {video, audio, player, errors} = setup(t);
  player.play(); await flush(); audio.emit('error');
  assert.equal(errors.length, 1); assert.equal(video.paused, true); assert.equal(player.wantsPlay, false);
  player.play(); await flush(); video.emit('ended');
  assert.equal(audio.paused, true); assert.equal(player.wantsPlay, false);
  player.play(); await flush(); player.dispose(); audio.emit('canplay'); player.tick();
  assert.equal(video.paused, true); assert.equal(audio.paused, true);
});
test('MP4 uses its own audio and transport', async t => {
  const {video, player} = setup(t, false);
  player.setVolume(0.2); player.play(); await flush();
  assert.equal(video.muted, false); assert.equal(video.volume, 0.2); assert.equal(video.paused, false);
  player.pause(); assert.equal(video.paused, true);
});
test('an autoplay rejection stops both and reports a retry message', async t => {
  const {video, audio, player, errors} = setup(t);
  audio.play = () => Promise.reject(Object.assign(new Error(), {name:'NotAllowedError'}));
  player.play(); await flush();
  assert.equal(video.paused, true); assert.equal(player.wantsPlay, false); assert.equal(errors.length, 1);
});
