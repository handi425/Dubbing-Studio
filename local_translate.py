"""Run the Argos English–Indonesian model locally with CTranslate2."""
import hashlib
import os
import re
import zipfile
import json
from pathlib import Path

import requests
from runtime_paths import DATA, RESOURCES, FROZEN

ROOT = DATA / "models"
_bundled_model = RESOURCES / "models" / "translate-en_id-1_9"
MODEL = _bundled_model if FROZEN and (_bundled_model / ".ready").is_file() else ROOT / "translate-en_id-1_9"
URL = "https://argos-net.com/v1/translate-en_id-1_9.argosmodel"
SHA256 = "fe5773201222806cfc802a094c5758ada6c25e10dbdd306d0c46bf200aac25fd"
_translator = None
_tokenizer = None
_multi = {}
ARGOS_VERSIONS = {'ar':'1_0','bg':'1_9','cs':'1_9_6','da':'1_9','de':'1_3','el':'1_9','es':'1_0',
 'et':'1_9','fi':'1_9','fr':'1_9','hi':'1_1','hu':'1_9','it':'1_0','ja':'1_1','ko':'1_1',
 'lt':'1_9','lv':'1_9','nl':'1_8','pl':'1_9','pt':'1_9','ro':'1_9','ru':'1_9','sk':'1_9',
 'sl':'1_9','sv':'1_5','tr':'1_5','uk':'1_4','vi':'1_9'}


def ensure_model(check=lambda: None, progress=lambda message: None):
    global _translator, _tokenizer
    if _translator is not None:
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    marker = MODEL / ".ready"
    if not marker.exists():
        archive = ROOT / "en-id.argosmodel"
        if not archive.exists():
            temporary = archive.with_suffix(".part")
            with requests.get(URL, stream=True, timeout=(10, 60)) as response:
                response.raise_for_status()
                size = 0
                with temporary.open("wb") as output:
                    for block in response.iter_content(1024 * 1024):
                        check()
                        output.write(block)
                        size += len(block)
                        progress(f"Mengunduh model terjemahan lokal: {size / 1024 ** 2:.0f} MB / sekitar 65 MB…")
            temporary.replace(archive)
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != SHA256:
            archive.unlink(missing_ok=True)
            raise ValueError("Unduhan model terjemahan tidak lengkap atau berubah. Coba lagi.")
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                check()
                target = (ROOT / member.filename).resolve()
                if not target.is_relative_to(ROOT.resolve()):
                    raise ValueError("Arsip model memiliki lokasi yang tidak valid.")
                package.extract(member, ROOT)
        marker.write_text(SHA256, encoding="ascii")
    progress("Memuat penerjemah Inggris–Indonesia di komputer…")
    import ctranslate2
    from sacremoses import MosesTokenizer, MosesDetokenizer, MosesPunctNormalizer
    from subword_nmt.apply_bpe import BPE
    with (MODEL / "bpe.model").open(encoding="utf-8") as codes:
        bpe = BPE(codes)
    _tokenizer = (MosesTokenizer(lang="en"), MosesDetokenizer(lang="id"), MosesPunctNormalizer(lang="en"), bpe)
    _translator = ctranslate2.Translator(str(MODEL / "model"), device="cpu", compute_type="int8",
                                         inter_threads=1, intra_threads=min(os.cpu_count() or 4, 8))


def translate(text, target='id', check=lambda: None, progress=lambda message: None):
    if target == 'en':
        return text
    if target != 'id':
        if target not in ARGOS_VERSIONS:
            raise ValueError('Penerjemah offline belum tersedia untuk bahasa ini.')
        return _translate_argos(text, target, check, progress)
    ensure_model(check, progress)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    batches = []
    for sentence in sentences:
        tokenizer, _, normalizer, bpe = _tokenizer
        tokens = bpe.segment_tokens(tokenizer.tokenize(normalizer.normalize(sentence)))
        # Bound source length explicitly so model defaults cannot silently drop long input.
        batches.extend(tokens[i:i + 180] for i in range(0, len(tokens), 180))
    results = _translator.translate_batch(batches, beam_size=4, replace_unknowns=True,
                                           max_input_length=0, max_decoding_length=512)
    return " ".join(_tokenizer[1].detokenize(" ".join(result.hypotheses[0]).replace("@@ ", "").split())
                    for result in results).strip()


def _translate_argos(text, target, check, progress):
    """Load a direct Argos EN→target package on demand; no SDK or cloud API."""
    for loaded in list(_multi):
        if loaded != target:
            _multi.pop(loaded, None)
    if target not in _multi:
        from runtime_paths import DATA
        import ctranslate2
        import sentencepiece
        folder = DATA / 'models' / f'argos-en-{target}'
        marker = folder / '.ready'
        if not marker.exists():
            folder.mkdir(parents=True, exist_ok=True)
            version = ARGOS_VERSIONS[target]
            url = f'https://argos-net.com/v1/translate-en_{target}-{version}.argosmodel'
            archive = folder.with_suffix('.argosmodel')
            temporary = archive.with_suffix('.part')
            if not archive.is_file():
                progress(f'Mengunduh model terjemahan offline {target.upper()} (sekali saja)…')
                with requests.get(url, stream=True, timeout=(15, 120)) as response:
                    response.raise_for_status()
                    with temporary.open('wb') as output:
                        for block in response.iter_content(1024 * 1024):
                            check()
                            output.write(block)
                temporary.replace(archive)
            source = None
            with zipfile.ZipFile(archive) as package:
                roots = {Path(item.filename).parts[0] for item in package.infolist()
                         if len(Path(item.filename).parts) > 1}
                if len(roots) != 1:
                    raise ValueError('Isi paket penerjemah offline tidak valid.')
                source = next(iter(roots))
                for name in ('metadata.json', 'sentencepiece.model'):
                    target_file = folder / source / name
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(package.read(f'{source}/{name}'))
                for item in package.infolist():
                    parts = Path(item.filename).parts
                    if len(parts) > 1 and parts[0] == source and parts[1] == 'model':
                        if Path(item.filename).is_absolute() or any(part in {'.', '..'} for part in parts):
                            raise ValueError('Paket model memiliki lokasi berkas yang tidak valid.')
                        target_file = folder.joinpath(*parts)
                        if not target_file.resolve().is_relative_to(folder.resolve()):
                            raise ValueError('Paket model memiliki lokasi berkas yang tidak valid.')
                        if item.is_dir():
                            target_file.mkdir(parents=True, exist_ok=True)
                        else:
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            with package.open(item) as source_stream, target_file.open('wb') as output:
                                while block := source_stream.read(1024 * 1024):
                                    check()
                                    output.write(block)
                (folder / '.ready').write_text(source, encoding='ascii')
            archive.unlink(missing_ok=True)
        source = marker.read_text(encoding='ascii') if marker.is_file() else f'en_{target}'
        model_dir = folder / source / 'model'
        if not model_dir.is_dir():
            raise ValueError('Model penerjemah offline tidak lengkap.')
        processor = sentencepiece.SentencePieceProcessor(model_file=str(folder / source / 'sentencepiece.model'))
        translator = ctranslate2.Translator(str(model_dir), device='cpu', compute_type='int8',
                    inter_threads=1, intra_threads=min(os.cpu_count() or 4, 4))
        _multi[target] = (processor, translator)
    processor, translator = _multi[target]
    output = []
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        check()
        tokens = processor.encode(sentence, out_type=str)
        if not tokens:
            continue
        result = translator.translate_batch([tokens], beam_size=4, replace_unknowns=True,
                    max_input_length=0, max_decoding_length=512)[0]
        output.append(processor.decode(result.hypotheses[0]).replace('▁', ' ').strip())
    translated = ' '.join(output).strip()
    if not translated:
        raise ValueError('Model penerjemah offline tidak menghasilkan teks.')
    return translated
