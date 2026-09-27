"""Bounded Google web requests with checked subtitle alignment and resumable batches."""
import hashlib
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

ENDPOINT = 'https://translate.googleapis.com/translate_a/single'
MAX_CHARS = 3500
MAX_ENCODED = 8500
MIN_INTERVAL = 5.0


def cache_key(text, target, source="en"):
    # Preserve compatibility with existing per-segment translation caches.
    return hashlib.sha256((('google' if source == 'en' else 'google:' + source + ':') + target + text).encode()).hexdigest()


def _split(text):
    """Split unusually long subtitle cues without exceeding the request budget."""
    remaining = text.strip()
    while remaining:
        low, high = 1, min(len(remaining), 2800)
        while low < high:
            mid = (low + high + 1) // 2
            if len(quote(remaining[:mid], safe='')) <= 7000:
                low = mid
            else:
                high = mid - 1
        cut = low
        if cut < len(remaining):
            spaces = list(re.finditer(r'\s+', remaining[:cut]))
            if spaces and spaces[-1].start() > cut // 2:
                cut = spaces[-1].start()
        part = remaining[:cut].strip()
        if part:
            yield part
        remaining = remaining[cut:].lstrip()


def _payload(parts):
    # Numeric markers avoid translating labels; the last marker detects truncation.
    base = 910000000
    source = '\n'.join(p[2] for p in parts)
    while any(str(base + i) in source for i in range(len(parts) + 1)):
        base += len(parts) + 1
    ids = [str(base + i) for i in range(len(parts) + 1)]
    text = '\n\n'.join(f'[[{ids[i]}]]\n{part[2]}' for i, part in enumerate(parts))
    return text + f'\n\n[[{ids[-1]}]]', ids


def _groups(parts):
    current = []
    for part in parts:
        candidate = current + [part]
        payload, _ = _payload(candidate)
        if current and (len(payload) > MAX_CHARS or len(quote(payload, safe='')) > MAX_ENCODED):
            yield current
            current = [part]
        else:
            current = candidate
    if current:
        yield current


def _parse(text, ids, allow_empty=False):
    marker = re.compile(r'\[\s*\[\s*(' + '|'.join(ids) + r')\s*\]\s*\]')
    matches = list(marker.finditer(text))
    if ([m.group(1) for m in matches] != ids
            or text[:matches[0].start()].strip() or text[matches[-1].end():].strip()):
        raise ValueError('Google mengubah atau memotong penanda kelompok subtitle. '
                         'Hasil kelompok ini belum diterapkan agar waktu subtitle tidak tertukar. Coba lagi nanti.')
    values = [text[a.end():b.start()].strip() for a, b in zip(matches, matches[1:])]
    if not allow_empty and any(not value for value in values):
        raise ValueError('Google mengembalikan bagian terjemahan kosong. Kelompok ini belum diterapkan.')
    return values


def _unfinished(original, translated, source, target):
    if not isinstance(translated, str) or not translated.strip():
        return True
    # Unchanged names, numbers and short terms can be valid translations.
    words = re.findall(r'[^\W\d_]+', original, re.UNICODE)
    substantial = len(words) >= 4 or (len(words) == 1 and len(words[0]) >= 20)
    normalize = lambda value: re.sub(r'\W+', '', value.casefold())
    return source != target and substantial and normalize(original) == normalize(translated)


def _wait(seconds, check):
    deadline = time.monotonic() + seconds
    while True:
        check()
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.2, left))


def _retry_after(value):
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


def _request(session, payload, target, check, progress, source="en"):
    for attempt in range(3):
        check()
        try:
            response = session.get(ENDPOINT, params={
                'client':'gtx', 'sl':source, 'tl':target, 'dt':'t', 'q':payload,
            }, timeout=(10, 45))
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt == 2:
                raise ValueError('Koneksi ke Google gagal. Kelompok yang sudah selesai tetap tersimpan; coba lagi nanti.') from error
            delay = 5 * (2 ** attempt)
        else:
            check()
            if response.status_code == 200:
                try:
                    data = response.json()
                    rows = data[0]
                    if not isinstance(rows, list) or not rows:
                        raise ValueError('Empty response')
                    values = [row[0] for row in rows]
                    if any(v is not None and not isinstance(v, str) for v in values):
                        raise ValueError('Invalid response')
                    return ''.join(v or '' for v in values)
                except (ValueError, TypeError, IndexError, KeyError) as error:
                    raise ValueError('Format respons Google tidak valid. Kelompok ini belum diterapkan.') from error
            if response.status_code == 403:
                raise ValueError('Google menolak akses (403). Hasil yang sudah selesai tersimpan. Coba lagi nanti atau pilih penerjemah lain.')
            if response.status_code != 429 and not 500 <= response.status_code < 600:
                raise ValueError(f'Google gagal merespons (HTTP {response.status_code}). Kelompok ini belum diterapkan.')
            delay = max((60 if response.status_code == 429 else 15) * (2 ** attempt),
                        _retry_after(response.headers.get('Retry-After')))
            if attempt == 2 or delay > 120:
                reason = 'membatasi permintaan (429)' if response.status_code == 429 else f'mengalami gangguan ({response.status_code})'
                raise ValueError(f'Google {reason}. Hasil yang sudah selesai tersimpan. Tunggu lalu klik Lanjutkan / coba lagi.')
        progress(f'Google belum tersedia. Menunggu {delay:.0f} detik sebelum mencoba kelompok yang sama…')
        _wait(delay, check)


def translate_segments(segments, target, cache, save_cache, check, progress, source="en"):
    """Retain good results; retry only missing/unchanged parts without batch markers."""
    pending = {}
    for segment in segments:
        key = cache_key(segment['en'], target, source)
        if _unfinished(segment['en'], cache.get(key), source, target):
            pending.setdefault(key, list(_split(segment['en'])))
    def part_key(text):
        return 'google-part-v2:' + cache_key(text, target, source)
    parts = [(key, index, text) for key, texts in pending.items() for index, text in enumerate(texts)]
    unresolved = [part for part in parts if _unfinished(part[2], cache.get(part_key(part[2])), source, target)]
    groups = list(_groups(unresolved))
    last_request = None
    def persist_parts(group, values):
        for (_, _, original), value in zip(group, values):
            if not _unfinished(original, value, source, target):
                cache[part_key(original)] = value.strip()
        # Save complete segments as soon as every part is available.
        for key, texts in pending.items():
            if all(not _unfinished(t, cache.get(part_key(t)), source, target) for t in texts):
                cache[key] = ' '.join(cache[part_key(t)] for t in texts)
        save_cache()
    with requests.Session() as session:
        def send(payload):
            nonlocal last_request
            check()
            if last_request is not None:
                _wait(max(0, MIN_INTERVAL - (time.monotonic() - last_request)), check)
            result = _request(session, payload, target, check, progress, source)
            last_request = time.monotonic()
            check()
            return result
        for number, group in enumerate(groups, 1):
            check()
            payload, ids = _payload(group)
            group_key = 'google-batch-v1:' + hashlib.sha256(((target if source == 'en' else source + ':' + target) + '\n' + payload).encode()).hexdigest()
            values = cache.get(group_key)
            valid_cache = isinstance(values, list) and len(values) == len(group) and all(isinstance(v, str) for v in values)
            if not valid_cache:
                progress(f'Menerjemahkan kelompok {number}/{len(groups)} ({len(group)} potongan teks)...')
                response = send(payload)
                try:
                    values = _parse(response, ids, allow_empty=True)
                except ValueError:
                    # Never guess alignment after Google alters the markers.
                    values = [''] * len(group)
                else:
                    cache[group_key] = values
            persist_parts(group, values)
            progress(f'Kelompok {number}/{len(groups)} diperiksa dan hasil berhasil disimpan.', number / max(1, len(groups)))
        # Retries use plain individual text, avoiding the marker failure mode.
        for attempt in range(1, 4):
            missing = {part_key(text): text for _, _, text in parts
                       if _unfinished(text, cache.get(part_key(text)), source, target)}
            if not missing:
                break
            for number, text in enumerate(missing.values(), 1):
                progress(f'Memeriksa ulang bagian tertinggal {number}/{len(missing)} (putaran {attempt}/3)...')
                value = send(text)
                persist_parts([('', 0, text)], [value])
    check()
    incomplete = []
    for number, segment in enumerate(segments, 1):
        value = cache.get(cache_key(segment['en'], target, source))
        if _unfinished(segment['en'], value, source, target):
            incomplete.append(number)
        else:
            segment['id'] = value
    if incomplete:
        raise ValueError(f'{len(incomplete)} bagian belum terkonfirmasi diterjemahkan setelah 3 putaran: '
                         + ', '.join(map(str, incomplete[:15]))
                         + '. Hasil berhasil tersimpan. Periksa teks atau lanjutkan nanti; dubbing belum dimulai.')
