from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, free_gpu, write_json


def drop_silent(words: list[dict], audio: np.ndarray, sr: int, floor_db: float) -> list[dict]:
    """Drop words whose audio is below floor_db: with the VAD filter off, Whisper invents text over
    silence (e.g. a Korean YouTube sign-off over 54 s of digital silence)."""
    keep = []
    for w in words:
        chunk = audio[int(w["start"] * sr):max(int(w["end"] * sr), int(w["start"] * sr) + 1)]
        if 20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9) >= floor_db:
            keep.append(w)
    return keep


def run(video: Path, work: Path, cfg: dict) -> None:
    import torch  # noqa: F401 - loads the CUDA DLLs (cublas) that ctranslate2 needs on Windows
    from faster_whisper import WhisperModel

    # faster-whisper's own word timestamps: on Korean they matched sentence pauses far better than
    # WhisperX's wav2vec2 alignment (11/11 vs 3/11 known pauses on FLEURS ko, 2026-10-05)
    # VAD filter and previous-text conditioning both made it skip whole sentences (12/12 vs 11/12, CER 9.9% vs ~20%)
    dev = device()
    model = WhisperModel("large-v3-turbo", device=dev, compute_type="float16" if dev == "cuda" else "int8")
    # the original mix, not the separated voice stem: separation artefacts doubled the error rate
    # (FLEURS ko + phone rings: CER 9.5% on the mix vs 19.8% on vocals.wav, 2026-10-06)
    wav = work / "audio.wav"
    segs, info = model.transcribe(str(wav), language=cfg["src"]["whisper"],
                                  word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
    words = [{"w": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3), "score": round(w.probability, 3)}
             for s in segs for w in s.words if w.word.strip()]
    del model
    free_gpu()
    audio, sr = sf.read(wav, dtype="float32")
    words = drop_silent(words, audio, sr, cfg["silence_db"])
    write_json(work / "words.json", {"language": cfg["src"]["whisper"], "duration": round(info.duration, 3), "words": words})
