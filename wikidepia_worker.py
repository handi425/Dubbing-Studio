"""Isolated Python 3.11 worker for Wikidepia's VITS model (one load per batch)."""
import contextlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'data' / 'models' / 'wikidepia'


def main():
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    import torch
    from g2p_id import G2P
    from num2words import num2words
    from TTS.utils.synthesizer import Synthesizer

    torch.set_num_threads(min(os.cpu_count() or 4, 8))
    phonemizer = G2P()
    synthesizer = Synthesizer(tts_checkpoint=str(MODEL/'checkpoint_1260000-inference.pth'),
                              tts_config_path=str(MODEL/'config.local.json'), use_cuda=False)
    progress = Path(manifest['progress'])
    for i, item in enumerate(manifest['items']):
        text = item['text']
        def number(match):
            value = match.group().replace(',', '.')
            return num2words(value, lang='id')
        text = re.sub(r'\d+(?:[.,]\d+)?', number, text).replace('%', ' persen')
        # The pretrained G2P predictor accepts at most 32 characters per token.
        text = re.sub(r'[A-Za-z]{32,}', lambda m: ' '.join(m[0][n:n+25] for n in range(0,len(m[0]),25)), text)
        phonemes = phonemizer(text)
        synthesizer.tts_model.length_scale = 1 / (1 + manifest['rate']/100)
        samples = synthesizer.tts(phonemes, speaker_name=manifest['speaker'], split_sentences=False)
        destination = Path(item['target'])
        temporary = destination.with_suffix('.partial.wav')
        synthesizer.save_wav(samples, str(temporary))
        temporary.replace(destination)
        progress.write_text(str(i+1), encoding='ascii')
    print('Wikidepia synthesis complete.', flush=True)


if __name__ == '__main__':
    main()
