"""One-time developer export. PyTorch/Coqui are NOT needed by the resulting app."""
import json
from pathlib import Path


def main():
    import onnx
    import torch
    from TTS.utils.synthesizer import Synthesizer

    root = Path(__file__).resolve().parent
    source = root / 'data/models/wikidepia'
    target = root / 'data/models/voice-onnx'
    target.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    synthesizer = Synthesizer(
        tts_checkpoint=str(source / 'checkpoint_1260000-inference.pth'),
        tts_config_path=str(source / 'config.local.json'), use_cuda=False)
    model = synthesizer.tts_model
    tokenizer = model.tokenizer
    if tokenizer.use_phonemes or tokenizer.use_eos_bos or synthesizer.tts_config.text_cleaner != 'basic_cleaners':
        raise ValueError('Unsupported tokenizer; export requires Wikidepia v1.2.')
    print('Exporting CPU voice model...', flush=True)
    temporary = target / 'voice.partial.onnx'
    with torch.no_grad():
        model.export_onnx(str(temporary), verbose=False)
    onnx.checker.check_model(str(temporary))
    metadata = {
        'version': 1, 'model': 'Wikidepia/indonesian-tts v1.2',
        'sample_rate': synthesizer.output_sample_rate,
        'vocab': tokenizer.characters.vocab,
        'add_blank': tokenizer.add_blank, 'blank_id': tokenizer.blank_id,
        'speakers': {key: model.speaker_manager.name_to_id[name] for key, name in
                     [('id-ID-ArdiNeural', 'ardi'), ('id-ID-GadisNeural', 'gadis')]},
        'noise_scale': float(model.inference_noise_scale),
        'noise_scale_dp': float(model.inference_noise_scale_dp),
    }
    temporary.replace(target / 'voice.onnx')
    (target / 'voice.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / 'MODEL-NOTICE.md').write_text(
        '# Indonesian offline voice\n\n'
        'ONNX conversion of Wikidepia/indonesian-tts v1.2.\n'
        'Source: https://github.com/Wikidepia/indonesian-tts\n'
        'Upstream restriction: DO NOT USE FOR COMMERCIAL PURPOSES!\n'
        'Ardi and Gadis were trained on Azure TTS samples. This is a local model, '
        'not the Microsoft service. Runtime phonemization uses g2p-id 0.0.4.\n', encoding='utf-8')
    print(f'Ready: {target}; model {(target / "voice.onnx").stat().st_size / 1024**2:.1f} MiB', flush=True)


if __name__ == '__main__':
    main()
