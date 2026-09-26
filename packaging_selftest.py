"""Exercise native libraries and real media output from the packaged executable."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback


def run():
    from runtime_paths import DATA, RESOURCES, FROZEN
    report = {"frozen": FROZEN, "data": str(DATA), "resources": str(RESOURCES), "checks": {}}
    checks = report["checks"]
    try:
        import app
        import engine
        import local_translate
        import supertonic_voice as local_voice
        import edge_tts
        import certifi
        import numpy as np
        from faster_whisper import WhisperModel
        from faster_whisper.vad import get_vad_model
        from tokenizers import Tokenizer
        import ctranslate2
        checks["imports"] = True
        if FROZEN:
            assert not DATA.is_relative_to(RESOURCES), "User data must survive bundle cleanup"
            assert Path(shutil.which("ffmpeg")).is_relative_to(RESOURCES)
            assert Path(shutil.which("ffprobe")).is_relative_to(RESOURCES)
        assert Path(certifi.where()).is_file()
        checks["bundled_ffmpeg"] = shutil.which("ffmpeg")
        translated = local_translate.translate("Hello. Welcome to this course.")
        assert translated and translated != "Hello. Welcome to this course."
        checks["local_translation"] = translated
        assert local_voice.ready(), 'Bundled offline voice is missing'
        assert client_info_default() == 'supertonic'
        vad = get_vad_model()
        vad(np.zeros(16384, dtype=np.float32))
        checks["whisper_vad"] = True
        client = app.app.test_client()
        for route in ("/", "/static/app.js", "/static/playback.js", "/static/style.css", "/api/info", "/api/playlists"):
            assert client.get(route).status_code == 200, route
        assert client.get("/api/info").json["ffmpeg"]
        checks["web_assets_and_api"] = True
        with tempfile.TemporaryDirectory(prefix="dubbing-smoke-", dir=DATA) as directory:
            root = Path(directory)
            source = root / "source.mp4"
            engine.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10:d=6",
                        "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-c:v", "libx264", "-c:a", "aac", str(source)])
            original_synthesize = engine.synthesize
            online = "--online-test" in sys.argv
            if not online:
                def tone(text, voice, rate, provider, target):
                    engine.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=600:duration=1", str(target)])
                engine.synthesize = tone
            try:
                job = dict(directory=directory, source=str(source), duration=6,
                           segments=[dict(start=1, end=5, en="Welcome.", id="Selamat datang.")],
                           **app.options({'tts': 'edge' if online else 'supertonic'}))
                for mode in ("audio", "video"):
                    updates = []
                    job["output_mode"] = mode
                    engine.render(job, lambda **values: updates.append(values), lambda: None)
                    output = root / ("hasil.mp3" if mode == "audio" else "hasil.mp4")
                    assert abs(engine.media_duration(output) - 6) < .2
                    assert updates[-1]["status"] == "done"
                    checks[f"render_{mode}"] = output.stat().st_size
                if not online:
                    import wave
                    import array
                    for voice in local_voice.VOICES:
                        job['voice'] = voice
                        local_voice.generate(job, lambda **values: None, lambda: None)
                        sample = root / 'speech' / (local_voice.cache_key('Selamat datang.', job) + '.wav')
                        with wave.open(str(sample), 'rb') as wav:
                            assert wav.getnframes() > wav.getframerate() / 4
                            assert max(map(abs, array.array('h', wav.readframes(wav.getnframes())))) > 100
                    checks['offline_voices'] = list(local_voice.VOICES)
                    assert 'torch' not in sys.modules and 'TTS' not in sys.modules
                    checks['no_pytorch'] = True
                if online:
                    checks["microsoft_tts"] = True
                    english = root / "english.mp3"
                    engine.synthesize("Hello, welcome to this course.", "en-US-AriaNeural", 0, "edge", english)
                    model = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2)
                    segments, _ = model.transcribe(str(english), language="en", vad_filter=True)
                    transcript = " ".join(segment.text.strip() for segment in segments)
                    assert "hello" in transcript.lower() or "welcome" in transcript.lower(), transcript
                    checks["whisper_transcription"] = transcript
            finally:
                engine.synthesize = original_synthesize
        report["ok"] = True
    except Exception:
        report.update(ok=False, error=traceback.format_exc())
    target = Path(os.environ.get("DUBBING_SELFTEST_REPORT", DATA.parent / "self-test.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    return 0 if report["ok"] else 1


def client_info_default():
    import app
    return app.app.test_client().get('/api/info').json['default_tts']
