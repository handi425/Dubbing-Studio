"""Subtitle, translation and time-aligned Microsoft dubbing pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path
from xml.sax.saxutils import escape

import requests

VOICES = {"id-ID-ArdiNeural": "Ardi · Pria", "id-ID-GadisNeural": "Gadis · Wanita"}
from supertonic_voice import VOICES as SUPERTONIC_VOICES
VOICES.update(SUPERTONIC_VOICES)
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
SAMPLE_RATE = 24000
ISO639_2 = {'en':'eng','ar':'ara','bg':'bul','cs':'ces','da':'dan','de':'deu','el':'ell','es':'spa',
 'et':'est','fi':'fin','fr':'fra','hi':'hin','hu':'hun','id':'ind','it':'ita','ja':'jpn','ko':'kor',
 'lt':'lit','lv':'lav','nl':'nld','pl':'pol','pt':'por','ro':'ron','ru':'rus','sk':'slk','sl':'slv',
 'sv':'swe','tr':'tur','uk':'ukr','vi':'vie'}


class Cancelled(Exception):
    pass


def run(command, check=lambda: None, timeout=7200):
    """Poll child processes so cancellation does not leave FFmpeg running."""
    import tempfile
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = time.monotonic()
        try:
            while True:
                check()
                try:
                    output, _ = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started > timeout:
                        raise RuntimeError("Proses melewati batas waktu. Coba video lebih pendek.")
            if process.returncode:
                errors.seek(0)
                detail = errors.read().decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError("Pemrosesan media gagal: " + detail)
            return output
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def probe(path, check=lambda: None):
    return json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", str(path)], check, 60))


def media_duration(path, check=lambda: None):
    result = float(probe(path, check)["format"]["duration"])
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Durasi video tidak valid.")
    return result


def timestamp_seconds(value):
    parts = value.replace(",", ".").split(":")
    return sum(float(part) * 60 ** i for i, part in enumerate(reversed(parts)))


def read_subtitles(path):
    raw = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    segments = []
    for block in re.split(r"\n\s*\n", raw):
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        for index, line in enumerate(lines):
            match = re.match(r"\s*([\d:.,]+)\s*-->\s*([\d:.,]+)", line)
            if match:
                text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[index + 1:])))
                text = re.sub(r"\s+", " ", text).strip()
                start, end = map(timestamp_seconds, match.groups())
                if text and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
                    segments.append({"start": start, "end": end, "en": text, "id": ""})
                break
    if not segments:
        raise ValueError("Subtitle tidak berisi teks dan waktu yang valid. Gunakan SRT atau VTT.")
    return sorted(segments, key=lambda item: item["start"])


def group_segments(segments):
    """Join cut-off subtitle sentences; preserve full sentences and useful timing."""
    grouped = []
    for segment in segments:
        current = dict(segment)
        if grouped:
            previous = grouped[-1]
            if (not re.search(r"[.!?][\"']?$", previous["en"])
                    and current["start"] - previous["end"] < 0.8
                    and current["end"] - previous["start"] <= 18
                    and len(previous["en"]) + len(current["en"]) < 500):
                previous["en"] += " " + current["en"]
                previous["end"] = max(previous["end"], current["end"])
                continue
        grouped.append(current)
    return grouped


def stamp(seconds, vtt=False):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{'.' if vtt else ','}{milliseconds:03}"


def write_subtitles(segments, directory, language='id'):
    for language in dict.fromkeys(("en", language)):
        for extension in ("srt", "vtt"):
            vtt = extension == "vtt"
            rows = ["WEBVTT\n"] if vtt else []
            for i, segment in enumerate(segments, 1):
                text = segment['en'] if language == 'en' else segment.get('id', '')
                rows.append(f"{i}\n{stamp(segment['start'], vtt)} --> {stamp(segment['end'], vtt)}\n"
                            f"{text}\n")
            (directory / f"subtitle.{language}.{extension}").write_text("\n".join(rows), encoding="utf-8")
    (directory / "transkrip.txt").write_text("\n\n".join(
        f"[{stamp(s['start'])}]\nEN: {s['en']}\n{language.upper()}: {s['id']}" for s in segments), encoding="utf-8")


def retry(action, check, label):
    for attempt in range(3):
        check()
        try:
            return action()
        except Cancelled:
            raise
        except Exception as error:
            if attempt == 2:
                raise RuntimeError(f"{label} gagal. Periksa internet atau pengaturan layanan. {error}") from error
            for _ in range((attempt + 1) * 10):
                check()
                time.sleep(0.2)


def translate_text(text, provider, target='id', check=lambda: None, progress=lambda message: None, openrouter_model=None):
    if provider == "local":
        from local_translate import translate
        translated = translate(text, target, check, progress)
    elif provider == 'openrouter':
        from openrouter_translate import translate
        check()
        translated = translate(text, target, model=openrouter_model)
        check()
    elif provider == "azure":
        key = os.environ.get("AZURE_TRANSLATOR_KEY")
        if not key:
            raise ValueError("Isi AZURE_TRANSLATOR_KEY dan AZURE_TRANSLATOR_REGION terlebih dahulu.")
        response = requests.post("https://api.cognitive.microsofttranslator.com/translate",
            params={"api-version": "3.0", "from": "en", "to": target},
            headers={"Ocp-Apim-Subscription-Key": key,
                     "Ocp-Apim-Subscription-Region": os.environ.get("AZURE_TRANSLATOR_REGION", "")},
            json=[{"Text": text}], timeout=(10, 45))
        response.raise_for_status()
        translated = response.json()[0]["translations"][0]["text"]
    else:
        # Public web endpoint; availability is not guaranteed. Azure is the official alternative.
        response = requests.get("https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": target, "dt": "t", "q": text}, timeout=(10, 45))
        response.raise_for_status()
        translated = "".join(part[0] or "" for part in response.json()[0])
    if not translated.strip():
        raise ValueError("Layanan mengembalikan terjemahan kosong.")
    return translated.strip()


def synthesize(text, voice, rate, provider, target):
    if provider == "azure":
        key = os.environ.get("AZURE_SPEECH_KEY")
        region = os.environ.get("AZURE_SPEECH_REGION", "")
        if not key or not re.fullmatch(r"[a-z0-9-]+", region):
            raise ValueError("Isi AZURE_SPEECH_KEY dan AZURE_SPEECH_REGION terlebih dahulu.")
        ssml = (f'<speak version="1.0" xml:lang="id-ID"><voice name="{voice}">'
                f'<prosody rate="{rate:+d}%">{escape(text)}</prosody></voice></speak>')
        response = requests.post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                     "User-Agent": "DubbingStudio"}, data=ssml.encode(), timeout=(10, 60))
        response.raise_for_status()
        target.write_bytes(response.content)
    else:
        import edge_tts
        async def save():
            await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=f"{rate:+d}%").save(str(target)), 90)
        asyncio.run(save())
    if not target.exists() or target.stat().st_size < 100:
        raise ValueError("Microsoft tidak menghasilkan audio.")


def prepare(job, update, check):
    directory = Path(job["directory"])
    source = Path(job["source"])
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("FFmpeg belum ditemukan. Pasang FFmpeg dan tambahkan folder bin ke PATH.")
    info = probe(source, check)
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError("File yang dipilih tidak memiliki video.")
    duration = media_duration(source, check)
    update(duration=duration, progress=3, message="Membaca video dan subtitle…")
    if job.get("subtitle"):
        segments = read_subtitles(job["subtitle"])
    else:
        update(progress=5, message="Memuat Whisper lokal. Pemakaian pertama mengunduh model; dapat memerlukan beberapa menit…")
        from faster_whisper import WhisperModel
        audio = directory / "source.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(audio)], check)
        check()
        model = WhisperModel(job["model"], device="cpu", compute_type="int8", cpu_threads=min(os.cpu_count() or 4, 8))
        stream, _ = model.transcribe(str(audio), language="en", vad_filter=True, beam_size=5)
        segments = []
        for segment in stream:
            check()
            if segment.text.strip():
                segments.append({"start": segment.start, "end": segment.end, "en": segment.text.strip(), "id": ""})
            update(progress=5 + 35 * segment.end / duration, message="Mentranskripsi ucapan bahasa Inggris…")
        audio.unlink(missing_ok=True)
    segments = group_segments([dict(s, end=min(s["end"], duration)) for s in segments if s["start"] < duration])
    if not segments:
        raise ValueError("Tidak ditemukan ucapan atau subtitle pada durasi video ini.")
    target_language = job.get('language', 'id')
    openrouter_model = None
    if job['translator'] == 'openrouter':
        from ai_settings import read_user_settings
        openrouter_model = read_user_settings()['openrouter_model']
    if job["translator"] == "local" and target_language == 'id':
        from local_translate import ensure_model
        ensure_model(check, lambda message: update(message=message))
    cache_path = directory / "translation-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    for i, segment in enumerate(segments):
        check()
        key = hashlib.sha256((job["translator"] + target_language + (openrouter_model or '') + segment["en"]).encode()).hexdigest()
        if key not in cache:
            cache[key] = retry(lambda: translate_text(segment["en"], job["translator"], target_language,
                check, lambda message: update(message=message), openrouter_model=openrouter_model), check, "Terjemahan")
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        segment["id"] = cache[key]
        update(progress=40 + 59 * (i + 1) / len(segments), message=f"Menerjemahkan {i + 1}/{len(segments)} bagian…")
    write_subtitles(segments, directory, target_language)
    result_label = "audio dubbing" if job.get("output_mode") == "audio" else "video dubbing"
    update(segments=segments, status="review", progress=100, message=f"Terjemahan siap. Periksa teks, lalu buat {result_label}.")


def tempo_filter(ratio):
    filters = []
    while ratio > 2:
        filters.append("atempo=2.0")
        ratio /= 2
    filters.append(f"atempo={max(0.5, ratio):.8f}")
    return ",".join(filters)


def render(job, update, check):
    directory = Path(job["directory"])
    segments = job["segments"]
    duration = job["duration"]
    cache_dir = directory / "speech"
    cache_dir.mkdir(exist_ok=True)
    local_voice = job["tts"] in {"wikidepia", "onnx", "supertonic"}
    if local_voice:
        if job["tts"] == "supertonic":
            from supertonic_voice import generate
        elif job["tts"] == "onnx":
            from local_voice import generate
        else:
            from wikidepia import generate
        generate(job, update, check)
    warnings = []
    timeline = directory / "dubbing.wav"
    # Stream PCM to disk: memory use stays bounded for long lessons.
    with wave.open(str(timeline), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        position = 0
        def silence(frames):
            while frames > 0:
                check()
                amount = min(frames, SAMPLE_RATE * 10)
                output.writeframesraw(b"\0\0" * amount)
                frames -= amount
        for i, segment in enumerate(segments):
            check()
            start = max(position, round(segment["start"] * SAMPLE_RATE))
            boundary = segments[i + 1]["start"] if i + 1 < len(segments) else duration
            available = boundary - start / SAMPLE_RATE
            if available < 0.05:
                raise ValueError(f"Waktu bagian {i + 1} bertumpuk. Perbaiki subtitle sumber.")
            key = hashlib.sha256(json.dumps([segment["id"], job["voice"], job["rate"], job["tts"]]).encode()).hexdigest()
            if job["tts"] == "supertonic":
                from supertonic_voice import cache_key
                key = cache_key(segment["id"], job)
            elif job["tts"] == "onnx":
                from local_voice import cache_key
                key = cache_key(segment["id"], job)
            speech = cache_dir / (f"{key}.wav" if local_voice else f"{key}.mp3")
            if not speech.exists():
                if local_voice:
                    raise RuntimeError(f"Audio lokal bagian {i + 1} belum dihasilkan. Coba lagi.")
                temporary = speech.with_suffix(".tmp.mp3")
                retry(lambda: synthesize(segment["id"], job["voice"], job["rate"], job["tts"], temporary), check, "Suara Microsoft")
                temporary.replace(speech)
            spoken_duration = media_duration(speech, check)
            ratio = max(1, spoken_duration / available)
            if ratio > 1.65:
                warnings.append(f"Bagian {i + 1}: suara dipercepat {ratio:.2f}×. Ringkas terjemahan agar lebih alami.")
            pcm = run(["ffmpeg", "-v", "error", "-i", str(speech), "-af", tempo_filter(ratio),
                       "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"], check, 120)
            max_frames = max(1, round(boundary * SAMPLE_RATE) - start)
            # Tiny filter-rounding overrun is padded back; do not silently truncate speech.
            if len(pcm) // 2 > max_frames:
                pcm = run(["ffmpeg", "-v", "error", "-i", str(speech), "-af",
                           tempo_filter(ratio * (len(pcm) / 2 / max_frames) * 1.015),
                           "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"], check, 120)
                if len(pcm) // 2 > max_frames:
                    raise ValueError(f"Audio bagian {i + 1} terlalu panjang. Ringkas terjemahannya.")
            silence(start - position)
            output.writeframesraw(pcm)
            position = start + len(pcm) // 2
            update(progress=(75 + 15 * (i + 1) / len(segments)) if local_voice else 90 * (i + 1) / len(segments),
                   message=f"Menyelaraskan suara {i + 1}/{len(segments)}…")
        silence(max(0, round(duration * SAMPLE_RATE) - position))
    target_language = job.get('language', 'id')
    write_subtitles(segments, directory, target_language)
    update(progress=93, message="Menggabungkan video, sulih suara, dan subtitle…")
    source = Path(job["source"])
    info = probe(source, check)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    if job.get("output_mode") == "audio":
        update(progress=95, message="Menyimpan sulih suara sebagai MP3…")
        command = ["ffmpeg", "-y", "-v", "error", "-i", str(timeline)]
        if job["original_volume"] > 0 and has_audio:
            command += ["-i", str(source), "-filter_complex",
                        f"[1:a:0]volume={job['original_volume']}[bg];[0:a:0][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[mix]",
                        "-map", "[mix]"]
        else:
            command += ["-map", "0:a:0"]
        command += ["-vn", "-c:a", "libmp3lame", "-b:a", "160k", "-t", str(duration),
                    str(directory / "hasil.partial.mp3")]
        run(command, check)
        check()
        (directory / "hasil.partial.mp3").replace(directory / "hasil.mp3")
        timeline.unlink(missing_ok=True)
        update(status="done", progress=100, warnings=warnings, message="Audio dubbing MP3 siap diputar.")
        return
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-i", str(timeline),
               "-i", str(directory / f"subtitle.{target_language}.srt"), "-map", "0:v:0"]
    if job["original_volume"] > 0 and has_audio:
        command += ["-filter_complex", f"[0:a:0]volume={job['original_volume']}[bg];[1:a:0][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[mix]",
                    "-map", "[mix]"]
    else:
        command += ["-map", "1:a:0"]
    command += ["-map", "2:s:0"]
    if has_audio:
        command += ["-map", "0:a:0", "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English original", "-disposition:a:1", "0"]
    codec = next(s["codec_name"] for s in info["streams"] if s["codec_type"] == "video")
    command += ["-c:v", "copy"] if codec == "h264" else ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
    command += ["-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text",
            "-metadata:s:a:0", f"language={target_language}", "-metadata:s:a:0", f"title={target_language.upper()} dubbing",
                "-disposition:a:0", "default", "-metadata:s:s:0", f"language={ISO639_2[target_language]}",
                "-movflags", "+faststart", "-t", str(duration), str(directory / "hasil.partial.mp4")]
    run(command, check)
    check()
    (directory / "hasil.partial.mp4").replace(directory / "hasil.mp4")
    timeline.unlink(missing_ok=True)
    update(status="done", progress=100, warnings=warnings, message="Video dubbing siap dipelajari.")
