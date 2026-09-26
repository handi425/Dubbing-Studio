"""Real CPU/offline smoke test and Windows peak working-set measurement."""
import array
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def guarded_worker(path):
    def offline(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
            raise RuntimeError('Network access is forbidden during offline voice verification')
    sys.addaudithook(offline)
    if '--supertonic' in sys.argv:
        from supertonic_voice import worker
    else:
        from local_voice import worker
    worker(path)
    assert 'torch' not in sys.modules and 'TTS' not in sys.modules
    read_memory = ctypes.WinDLL('psapi').GetProcessMemoryInfo
    read_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    read_memory.restype = wintypes.BOOL
    memory = MemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    assert read_memory(wintypes.HANDLE(-1), ctypes.byref(memory), memory.cb)
    Path(path).with_suffix('.metrics.json').write_text(json.dumps(
        {'peak_working_set_mib': round(memory.PeakWorkingSetSize / 1024**2, 1)}), encoding='utf-8')


class MemoryCounters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                                           'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
                                           'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                                           'PagefileUsage', 'PeakPagefileUsage')]


def main():
    supertonic = '--supertonic' in sys.argv
    if supertonic:
        from supertonic_voice import model_directory
    else:
        from local_voice import model_directory
    root = ROOT / ('build/supertonic-verification' if supertonic else 'build/voice-verification')
    root.mkdir(parents=True, exist_ok=True)
    report = {'model_mib': sum(p.stat().st_size for p in model_directory().rglob('*.onnx')) / 1024**2, 'runs': []}
    text = 'Selamat datang di Dubbing Studio. Suara ini dibuat langsung di komputer tanpa koneksi internet.'
    voices = ('M1', 'F1') if supertonic else ('ardi', 'gadis')
    for voice in voices:
        for rate in (0, -30, 30):
            targets = [(text, root / f'{voice}-{rate}.wav')]
            if rate == 0:
                targets += [('Halo.', root / f'{voice}-short.wav'),
                            ('Harga naik 12,5% dari 1.000 rupiah. ' * 15, root / f'{voice}-long.wav')]
            request = root / 'request.json'
            request.write_text(json.dumps(dict(
                model=str(model_directory()), voice=f'supertonic-{voice}' if supertonic else f'id-ID-{voice.capitalize()}Neural', rate=rate,
                progress=str(root / 'progress.txt'),
                items=[dict(text=value, target=str(target)) for value, target in targets]
            )), encoding='utf-8')
            started = time.perf_counter()
            process = subprocess.run([sys.executable, '-X', 'utf8', __file__,
                                      *(['--supertonic'] if supertonic else []), '--worker', str(request)],
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=300)
            assert process.returncode == 0, 'Offline voice worker failed'
            elapsed = time.perf_counter() - started
            durations = []
            for _, target in targets:
                with wave.open(str(target), 'rb') as wav:
                    assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
                    samples = array.array('h', wav.readframes(wav.getnframes()))
                    assert samples and max(map(abs, samples)) > 100
                    durations.append(wav.getnframes() / wav.getframerate())
            item = dict(voice=voice, rate=rate, seconds=round(elapsed, 2),
                        audio_seconds=round(sum(durations), 2), first_audio_seconds=round(durations[0], 2),
                        **json.loads(request.with_suffix('.metrics.json').read_text(encoding='utf-8')))
            report['runs'].append(item)
            print(json.dumps(item), flush=True)
    for voice in voices:
        lengths = {r['rate']: r['first_audio_seconds'] for r in report['runs'] if r['voice'] == voice}
        assert lengths[-30] > lengths[0] > lengths[30], lengths
    report.update(ok=True, network_forbidden=True, no_pytorch=True)
    (root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    if '--worker' in sys.argv:
        guarded_worker(sys.argv[-1])
    else:
        main()
