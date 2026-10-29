import difflib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, ffmpeg, free_gpu, read_json, write_json
from .tags import VOCAL_TOKENS, not_performed, shape_audio, speed, text_for_tts

# Chatterbox pins torch 2.6 / numpy < 2, so it lives in its own environment next to .venv (see README)
CHATTERBOX_PY = Path(__file__).parents[2] / ".venv-chatterbox" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _kokoro(texts: list[str], tts: dict):
    from kokoro import KPipeline

    pipe = KPipeline(lang_code=tts["voice"][0])  # Kokoro voice ids start with their accent code: a=US, b=UK, ...
    for text in texts:
        yield np.concatenate([np.asarray(a) for _, _, a in pipe(text, voice=tts["voice"], speed=1.0)]), 24000


def _mms(texts: list[str], tts: dict):
    # Meta MMS-TTS (VITS), one model per language, CC BY-NC 4.0; non-Latin scripts need `uroman`
    import torch
    from transformers import AutoTokenizer, VitsModel

    dev = device()
    tok = AutoTokenizer.from_pretrained(tts["voice"])
    model = VitsModel.from_pretrained(tts["voice"]).to(dev)
    torch.manual_seed(0)  # VITS samples noise: fixed seed keeps reruns identical
    for text in texts:
        ids = tok(text, return_tensors="pt").to(dev)
        if ids["input_ids"].shape[1] == 0:  # nothing pronounceable
            yield np.zeros(1, dtype="float32"), model.config.sampling_rate
            continue
        with torch.no_grad():
            yield model(**ids).waveform[0].cpu().numpy(), model.config.sampling_rate


def _chatterbox(texts: list[str], tts: dict):
    # Chatterbox (MIT): Turbo for English, Multilingual for tts["lang"]; the built-in voice or a reference recording.
    # Run by chatterbox_worker.py in .venv-chatterbox. -I: the worker's folder (src/dubbe) must not shadow that environment
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([str(CHATTERBOX_PY), "-I", str(Path(__file__).with_name("chatterbox_worker.py"))],
                           input=json.dumps({"texts": texts, "out_dir": tmp, "lang": tts.get("lang", "en"),
                                             "prompt": tts.get("prompt"), "prompts": tts.get("prompts")}), capture_output=True,
                           text=True, encoding="utf8", errors="replace")
        if p.returncode != 0:
            raise SystemExit("Chatterbox failed: " + ((p.stderr.strip().splitlines() or ["no output"])[-1]))
        clips = []
        for i in range(len(texts)):
            audio, sr = sf.read(Path(tmp) / f"{i}.wav", dtype="float32")
            clips.append((cut_tail(audio, sr), sr))
    yield from cut_babble(clips, texts, tts.get("lang", "en"))


# one adapter per engine, not per language
ENGINES = {"kokoro": _kokoro, "mms": _mms, "chatterbox": _chatterbox, "chatterbox_ml": _chatterbox}

PROMPT_TEXT = ("Hello, this is the voice you will hear in the dub. I speak at an easy pace, with clear words and a calm tone, "
               "so every sentence sounds natural.")
PROMPTS = Path(os.environ.get("DUBBE_CACHE", Path.home() / ".cache" / "dubbe")) / "prompts"


def sample_name(voice: str, lang: str, info: dict) -> str:
    """File name of a voice's sample on the website (samples/<name>.wav): an English preset speaking another language,
    and each language's built-in voice, get the language added."""
    return voice.replace("/", "_") + (f"-{lang}" if info.get("prompt") or lang not in ("en", "ko") else "")


def preset_prompt(voice: str) -> Path:
    """A reference recording of an English preset (Kokoro reading PROMPT_TEXT), so Chatterbox can speak another language
    in that voice - a synthetic voice, nobody's real one (test-results C24). Made once, then cached."""
    f = PROMPTS / f"{voice}.wav"
    if not f.exists():
        audio, sr = next(_kokoro([PROMPT_TEXT], {"voice": voice}))
        f.parent.mkdir(parents=True, exist_ok=True)
        sf.write(f, trim(audio), sr)
    return f


def tts_cfg(data: dict, cfg: dict, prompt: Path | None = None, speaker: str = "S1") -> dict:
    """Target-language TTS settings with the voice chosen for the speaker (voice stage, C10) - or, when a
    reviewer tagged a sentence with a vocal tag ([laugh] ...) or [question], the language's `expressive` engine
    for the whole video, so the dub keeps one voice. [question]: Chatterbox Turbo's end rose in 11 of 12 English
    test questions, Kokoro's in at most 5 of 12 even with DUBBE's glide (test-results C19c).
    A consented voice clone ("clone:<id>" from the user's voices, "video:<speaker>" made from this video with consent;
    web/clones.py) speaks only when its reference recording was put at `prompt` for this job; otherwise a preset does.
    Everything is per speaker: their voice, and the tags in their own sentences."""
    tts = cfg["tgt"]["tts"]
    chosen = data.get("speakers", {}).get(speaker, {}).get("voice")
    if (chosen or "").startswith(("clone:", "video:")) and prompt and Path(prompt).exists() and CHATTERBOX_PY.exists():
        return {**tts, "engine": tts["clone"], "voice": chosen, "prompt": str(prompt)}
    preset = chosen if chosen in tts.get("voices", {}) else tts["voice"]  # no voice chosen yet: the language's default
    if (tts.get("voices", {}).get(preset) or {}).get("prompt") and CHATTERBOX_PY.exists():  # an English preset, in this language
        return {**tts, "engine": tts["clone"], "voice": preset, "prompt": str(preset_prompt(preset))}
    if tts["engine"].startswith("chatterbox") and not CHATTERBOX_PY.exists():
        if "fallback" not in tts:
            raise SystemExit(f"Speaking '{tts.get('lang')}' needs Chatterbox: set up .venv-chatterbox (README)")
        tts = {**tts, **tts["fallback"]}  # Korean without .venv-chatterbox: MMS
    # only tags a person chose switch the voice: tags heard in the original (emotion stage) are spoken by this voice
    asked = {t for s in data["segments"] if s.get("speaker", "S1") == speaker and (s.get("tags_edited") or "auto_tags" not in s)
             for t in s.get("tags") or []}
    # ponytail: chatterbox is the only expressive engine; check its own environment when a second one arrives
    if asked & (set(VOCAL_TOKENS.get(tts.get("expressive"), {})) | {"question"}) and tts.get("expressive") and CHATTERBOX_PY.exists():
        return {**tts, "engine": tts["expressive"], "voice": "built-in"}
    return {**tts, **({"voice": chosen} if chosen in tts.get("voices", {}) else {})}


def trim(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Cut leading/trailing near-silence so measured durations are honest."""
    loud = np.flatnonzero(np.abs(audio) > threshold)
    return audio[loud[0]:loud[-1] + 1] if loud.size else audio[:0]


def cut_tail(audio: np.ndarray, sr: int, pad_s: float = .15) -> np.ndarray:
    """Chatterbox often goes on after the sentence: seconds of near-silence with faint noise or a click. Cut pad_s after
    the LAST speech that Silero VAD (bundled with faster-whisper) finds, so pauses inside the text stay. 36 test clips:
    87.8 -> 56.5 s, no word lost; cutting at the first long silence turned "What? ... are you all insane?" into "What?"."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if len(audio) < 2:
        return audio
    x = np.interp(np.arange(0, len(audio), sr / 16000), np.arange(len(audio)), audio).astype("float32")  # VAD wants 16 kHz
    speech = get_speech_timestamps(x, VadOptions(min_silence_duration_ms=100, speech_pad_ms=0))
    return audio[:int((speech[-1]["end"] / 16000 + pad_s) * sr)] if speech else audio


def _letters(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if unicodedata.category(c)[0] in "LMN")


def babble_cut(words: list[tuple[str, float]], text: str) -> float | None:
    """Where to cut a sentence Chatterbox went on after: words = what Whisper heard, (word, end time). The prefix that
    matches the text best ends the sentence; cut there only when clearly more was heard than the text holds (a misheard
    last word is not babble)."""
    want = _letters(re.sub(r"\[[a-z_ ]+\]", "", text))  # without Chatterbox's sound tokens
    heard = [_letters("".join(w for w, _ in words[:k])) for k in range(len(words) + 1)]
    if not want or len(heard[-1]) <= len(want) * 1.15 + 2:
        return None
    k = max(range(1, len(words) + 1), key=lambda k: difflib.SequenceMatcher(None, want, heard[k]).ratio())
    good = difflib.SequenceMatcher(None, want, heard[k]).ratio() >= .6
    return words[k - 1][1] if good and k < len(words) else None


def cut_babble(clips: list[tuple[np.ndarray, int]], texts: list[str], lang: str):
    """Chatterbox sometimes keeps talking after the sentence in made-up words ("... l'année dernière ? N'enfin, s'y mitrait.":
    French with bf_alice, 2 of 6 sentences; Korean af_alloy most sentences). Whisper listens to each sentence and the audio
    ends 0.15 s after the last word of the text (test-results C25)."""
    import torch  # noqa: F401 - loads the CUDA DLLs (cublas) that ctranslate2 needs on Windows
    from faster_whisper import WhisperModel

    dev = device()
    model = WhisperModel("large-v3-turbo", device=dev, compute_type="float16" if dev == "cuda" else "int8")
    for (audio, sr), text in zip(clips, texts):
        x = np.interp(np.arange(0, len(audio), sr / 16000), np.arange(len(audio)), audio).astype("float32")
        segs, _ = model.transcribe(x, language=lang, word_timestamps=True, condition_on_previous_text=False)
        end = babble_cut([(w.word, w.end) for s in segs for w in s.words], text)
        yield (audio[:int((end + .15) * sr)] if end else audio), sr
    del model
    free_gpu()


def finish(path: Path, audio: np.ndarray, sr: int, tags: list[str]) -> float:
    """Apply the reviewer's delivery tags ([soft], [pause], [slow] ...) and write the sentence; returns its length."""
    sf.write(path, shape_audio(audio, sr, tags), sr)
    if speed(tags) != 1.0:
        tmp = path.with_suffix(".tag.wav")
        ffmpeg("-i", str(path), "-filter:a", f"atempo={speed(tags)}", str(tmp))  # keeps pitch
        tmp.replace(path)
    return round(sf.info(path).duration, 3)


def synth(data: dict, cfg: dict, work: Path, items: list[tuple[dict, str]]):
    """Speak (segment, text) pairs, each speaker with their own voice: yields (segment, audio, sr, tts settings, speaker).
    A clone's recording for a speaker is at work/voice_prompt_<speaker>.wav for the length of the job (the website)."""
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(it[0].get("speaker", "S1"), []).append(it)
    for sp, its in groups.items():
        tts = tts_cfg(data, cfg, work / f"voice_prompt_{sp}.wav", sp)
        if tts["engine"] not in ENGINES:
            raise SystemExit(f"TTS engine '{tts['engine']}' is not implemented yet (have: {', '.join(ENGINES)})")
        texts = [text_for_tts(t, s.get("tags") or [], tts["engine"], tts.get("lang", "")) for s, t in its]
        for (s, _), (audio, sr) in zip(its, ENGINES[tts["engine"]](texts, tts)):
            yield s, audio, sr, tts, sp


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    out_dir = work / "tts"
    out_dir.mkdir(exist_ok=True)
    used = {}
    for s, audio, sr, tts, sp in synth(data, cfg, work, [(s, s["tgt_text"] or "") for s in data["segments"]]):
        s["tts_dur"] = finish(out_dir / f"{s['id']}.wav", trim(audio), sr, s.get("tags") or [])
        s["tags_not_performed"] = not_performed(s.get("tags") or [], tts["engine"])
        used[sp] = {"engine": tts["engine"], "voice": tts["voice"]}
    for sp, u in used.items():
        data.setdefault("speakers", {}).setdefault(sp, {})["used"] = u
    data["tts_used"] = used.get("S1") or next(iter(used.values()), {})  # the main speaker's, for older readers
    free_gpu()
    write_json(work / "segments.json", data)
