from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, free_gpu, read_json, write_json

MAX_CHUNK = 28.0  # s: at most one Whisper window, so its long-form seek cannot jump over speech (test C29)
MIN_CHUNK = 1.0   # s: shorter pieces give Whisper too little to go on; they stay joined to the previous one
MIN_TURN = 0.5    # s: shorter turns are diarization flicker, not a new speaker - KOR news run 12: 16 such turns cut
                  # a child's sentence into 1-2 s pieces and Whisper invented "다음 영상에서 만나요" (run 11: 4, right)


def whisper_model(name: str) -> str:
    """faster-whisper loads its own sizes ("large-v3") or CTranslate2 folders. A Hugging Face Whisper fine-tune (Uzbek:
    islomov/rubaistt_v2_medium, FLEURS CER 2.7 % vs 25 % for large-v3, C43) is converted once into the cache."""
    if "/" not in name:
        return name
    import os
    out = Path(os.environ.get("DUBBE_CACHE", Path.home() / ".cache" / "dubbe")) / "ct2" / name.replace("/", "--")
    if not (out / "model.bin").exists():
        from ctranslate2.converters import TransformersConverter
        from transformers import WhisperTokenizerFast
        TransformersConverter(name, copy_files=["preprocessor_config.json"]).convert(str(out), quantization="float16", force=True)
        WhisperTokenizerFast.from_pretrained(name).save_pretrained(out)  # tokenizer.json, which faster-whisper reads
    return str(out)


def speaker_changes(turns: list[dict]) -> list[float]:
    """Times where diarization moves to another speaker: the middle of the gap between their turns, or the new
    turn's start when they overlap. Used only as places to cut the audio, never as labels."""
    turns = [t for t in turns if t["end"] - t["start"] >= MIN_TURN]
    return [(a["end"] + b["start"]) / 2 if b["start"] > a["end"] else b["start"]
            for a, b in zip(turns, turns[1:]) if a["speaker"] != b["speaker"]]


def plan_chunks(duration: float, speech: list[tuple[float, float]], changes: list[float],
                max_len: float = MAX_CHUNK, min_len: float = MIN_CHUNK) -> list[tuple[float, float]]:
    """Cut [0, duration] into pieces of at most max_len that cover ALL of it (nothing is dropped): always at a speaker
    change, otherwise in the middle of the last pause (gap between VAD speech regions) before max_len, or hard at
    max_len when there is no pause."""
    pauses = [(a[1] + b[0]) / 2 for a, b in zip(speech, speech[1:])]
    hard = sorted(c for c in changes if 0 < c < duration)
    out, start = [], 0.0
    while start < duration - 1e-6:
        limit = min(start + max_len, duration)
        end = next((c for c in hard if start + min_len <= c < limit), None)
        if end is None:
            soft = [p for p in pauses if start + min_len <= p < limit]
            end = duration if limit >= duration else (soft[-1] if soft else limit)
        out.append((round(start, 3), round(end, 3)))
        start = end
    return out


def drop_silent(words: list[dict], audio: np.ndarray, sr: int, floor_db: float) -> list[dict]:
    """Drop words whose audio is below floor_db: with the VAD filter off, Whisper invents text over
    silence (e.g. a Korean YouTube sign-off over 54 s of digital silence). The floor moves down with a quiet recording -
    at most 30 dB under its median word: FLEURS readers at -60 to -65 dB lost whole sentences to a fixed -60 dB (C43)."""
    levels = [20 * np.log10(np.sqrt(np.mean(audio[int(w["start"] * sr):max(int(w["end"] * sr), int(w["start"] * sr) + 1)] ** 2)) + 1e-9)
              for w in words]
    # ponytail: the median assumes most words are real; a video that is mostly silence with invented text would keep them
    floor = min(floor_db, float(np.median(levels)) - 30) if levels else floor_db
    return [w for w, lv in zip(words, levels) if lv >= floor]


def run(video: Path, work: Path, cfg: dict) -> None:
    import torch  # noqa: F401 - loads the CUDA DLLs (cublas) that ctranslate2 needs on Windows
    from faster_whisper import WhisperModel
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    # faster-whisper's own word timestamps: on Korean they matched sentence pauses far better than
    # WhisperX's wav2vec2 alignment (11/11 vs 3/11 known pauses on FLEURS ko, 2026-10-05)
    # VAD filter and previous-text conditioning both made it skip whole sentences (12/12 vs 11/12, CER 9.9% vs ~20%)
    dev = device()
    model = WhisperModel(whisper_model(cfg["src"].get("asr_model", "large-v3-turbo")), device=dev,
                         compute_type="float16" if dev == "cuda" else "int8")
    # the original mix, not the separated voice stem: separation artefacts doubled the error rate
    # (FLEURS ko + phone rings: CER 9.5% on the mix vs 19.8% on vocals.wav, 2026-10-06)
    wav = work / "audio.wav"
    audio, sr = sf.read(wav, dtype="float32")  # 16 kHz mono from extract
    # One pass over a long file let Whisper's 30 s seek jump over whole interview clips (KOR news: 0 words in three
    # parts that it transcribed perfectly on their own, C29). So the audio is cut into pieces of at most one window, at
    # speaker changes (diarize runs first) and pauses: Whisper does best on one voice per piece - cutting at pauses
    # alone lost the interviews again (KOR 18/0/0 words, FLEURS CER 15.1% vs 9.5%, C33). The turns only place the
    # cuts; every second is still transcribed and `speakers` decides who said each word. A piece is transcribed from
    # the first to the last sound the VAD or the diarization hears in it (+0.2 s): silence left at a piece's end made
    # Whisper invent YouTube sign-offs ("영상편집 및 자료조사", FLEURS CER 13.5% -> 8.5% trimmed). Only pieces where
    # neither hears speech are skipped.
    speech = [(s["start"] / sr, s["end"] / sr)
              for s in get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))]
    diar = work / "diarization.json"
    turns = read_json(diar)["turns"] if diar.exists() else []
    heard = speech + [(t["start"], t["end"]) for t in turns]
    words = []
    for a, b in plan_chunks(len(audio) / sr, speech, speaker_changes(turns)):
        inside = [(s, e) for s, e in heard if s < b and e > a]
        if not inside:
            continue
        a, b = max(a, min(s for s, _ in inside) - 0.2), min(b, max(e for _, e in inside) + 0.2)
        segs, _ = model.transcribe(audio[int(a * sr):int(b * sr)], language=cfg["src"]["whisper"],
                                   word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
        words += [{"w": w.word.strip(), "start": round(a + w.start, 3), "end": round(a + w.end, 3), "score": round(w.probability, 3)}
                  for s in segs for w in s.words if w.word.strip()]
    del model
    free_gpu()
    words = drop_silent(words, audio, sr, cfg["silence_db"])
    write_json(work / "words.json", {"language": cfg["src"]["whisper"], "duration": round(len(audio) / sr, 3), "words": words})
