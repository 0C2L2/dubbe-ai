from pathlib import Path

import soundfile as sf

from . import db, device, ffmpeg, free_gpu


def run(video: Path, work: Path, cfg: dict) -> None:
    """Split the original audio and keep the background stem (music, effects, a phone ringing)
    that mux puts back under the dubbed voice. The voice stem is not used for ASR: its artefacts
    doubled Whisper's error rate, so ASR reads the original mix."""
    if not cfg["keep_background"]:
        for f in ("background.wav", "vocals.wav"):
            (work / f).unlink(missing_ok=True)  # mux falls back to voice-only
        return

    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    if not (work / "original.wav").exists():  # work folder from before this stage existed
        ffmpeg("-i", str(video), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(work / "original.wav"))
    model = get_model("htdemucs")  # Demucs v4, MIT licence
    audio, sr = sf.read(work / "original.wav", dtype="float32")  # 44.1 kHz stereo from extract
    x = torch.from_numpy(audio.T.copy())[None]
    mean, std = x.mean(), x.std() + 1e-8
    with torch.no_grad():
        out = apply_model(model, (x - mean) / std, device=device(), progress=False)[0] * std + mean
    vocals = out[model.sources.index("vocals")]
    bg = (out.sum(0) - vocals).cpu().numpy().T
    if db(bg) < db(audio) - cfg["background_floor_db"]:
        # e.g. a voice-only fan dub: the "background" is only separation residue (hiss, DC, 43 Hz hum)
        print(f"         no real background ({db(bg) - db(audio):.0f} dB below the original): voice-only mix")
        (work / "background.wav").unlink(missing_ok=True)
    else:
        sf.write(work / "background.wav", bg, sr)
    sf.write(work / "vocals44.wav", vocals.cpu().numpy().T, sr)
    del model, out, vocals
    free_gpu()
    # voice stem at 16 kHz mono for pitch analysis (voice stage) - not for ASR, see asr.py
    ffmpeg("-i", str(work / "vocals44.wav"), "-ac", "1", "-ar", "16000", str(work / "vocals.wav"))
    (work / "vocals44.wav").unlink()
