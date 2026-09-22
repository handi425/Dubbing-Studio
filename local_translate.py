"""Run the Argos English–Indonesian model locally with CTranslate2."""
import hashlib
import os
import re
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent / "data" / "models"
MODEL = ROOT / "translate-en_id-1_9"
URL = "https://argos-net.com/v1/translate-en_id-1_9.argosmodel"
SHA256 = "fe5773201222806cfc802a094c5758ada6c25e10dbdd306d0c46bf200aac25fd"
_translator = None
_tokenizer = None


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


def translate(text):
    ensure_model()
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
