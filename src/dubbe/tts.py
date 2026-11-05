import difflib
import hashlib
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
from .tags import INSTRUCT_END, MING_TO_COSY, NAVOIY_CALM, VOCAL_TOKENS, dubbe_tags, not_performed, shape_audio, speed, text_for_tts

# Chatterbox pins torch 2.6 / numpy < 2, so it lives in its own environment next to .venv (see README)
CHATTERBOX_PY = Path(__file__).parents[2] / ".venv-chatterbox" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
# CosyVoice 3 pins torch 2.3: its own environment too, with its code checked out in .cosyvoice (README)
COSYVOICE_PY = Path(__file__).parents[2] / ".venv-cosyvoice" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
COSYVOICE_REPO = Path(__file__).parents[2] / ".cosyvoice"
COSYVOICE_MODEL = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
# Ming-3.0-tts pins torch 2.6 / transformers 4.46: its own environment, its code checked out in .ming (README)
MING_PY = Path(__file__).parents[2] / ".venv-ming" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MING_REPO = Path(__file__).parents[2] / ".ming"
MING_MODEL = "inclusionAI/Ming-3.0-tts-0.5B"
# Navoiy TTS (Uzbek, Apache-2.0): CosyVoice 2 with its own LLM weights, run by cosyvoice_worker.py in .venv-cosyvoice (C43)
NAVOIY_MODEL, NAVOIY_LLM = "FunAudioLLM/CosyVoice2-0.5B", ("aisha-org/navoiy-tts", "emotion_600h_joint.pt")
PROMPTED = ("cosyvoice", "ming", "navoiy")  # engines that speak every voice from a reference recording


def env_py(engine: str) -> Path | None:
    """The Python of an engine that runs in its own environment (None: it runs in .venv)."""
    return {"cosyvoice": COSYVOICE_PY, "navoiy": COSYVOICE_PY, "ming": MING_PY, "chatterbox": CHATTERBOX_PY,
            "chatterbox_ml": CHATTERBOX_PY}.get(engine)


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
    for i, text in enumerate(texts):
        torch.manual_seed((tts.get("seeds") or [0] * len(texts))[i])  # VITS samples noise: same take, same clip; a retake differs
        ids = tok(text, return_tensors="pt").to(dev)
        if ids["input_ids"].shape[1] == 0:  # nothing pronounceable
            yield np.zeros(1, dtype="float32"), model.config.sampling_rate
            continue
        with torch.no_grad():
            yield model(**ids).waveform[0].cpu().numpy(), model.config.sampling_rate


def _piper(texts: list[str], tts: dict):
    # Piper (MIT) voices from rhasspy/piper-voices, CPU. Kazakh: kk_KZ-issai-high (ISSAI corpus, CC BY 4.0), 6 speakers -
    # voice "issai-<n>" is speaker n; FLEURS round-trip CER 7.3 % vs MMS 11.7 % (C43). No reference recording: no cloning
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig

    hf_hub_download("rhasspy/piper-voices", tts["model"] + ".onnx.json")
    voice = PiperVoice.load(hf_hub_download("rhasspy/piper-voices", tts["model"] + ".onnx"))
    cfg = SynthesisConfig(speaker_id=int(tts["voice"].rsplit("-", 1)[1]))
    for text in texts:
        chunks = list(voice.synthesize(text, syn_config=cfg)) if text.strip() else []
        yield (np.concatenate([c.audio_float_array for c in chunks]) if chunks else np.zeros(1, "float32")), voice.config.sample_rate


def _chatterbox(texts: list[str], tts: dict):
    # Chatterbox (MIT): Turbo for English, Multilingual for tts["lang"]; the built-in voice or a reference recording.
    # Run by chatterbox_worker.py in .venv-chatterbox. -I: the worker's folder (src/dubbe) must not shadow that environment
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([str(CHATTERBOX_PY), "-I", str(Path(__file__).with_name("chatterbox_worker.py"))],
                           input=json.dumps({"texts": texts, "out_dir": tmp, "lang": tts.get("lang", "en"),
                                             "prompt": tts.get("prompt"), "prompts": tts.get("prompts"),
                                             "seeds": tts.get("seeds")}), capture_output=True,
                           text=True, encoding="utf8", errors="replace")
        if p.returncode != 0:
            raise SystemExit("Chatterbox failed: " + ((p.stderr.strip().splitlines() or ["no output"])[-1]))
        clips = []
        for i in range(len(texts)):
            audio, sr = sf.read(Path(tmp) / f"{i}.wav", dtype="float32")
            clips.append((cut_tail(audio, sr), sr))
    yield from cut_babble(clips, texts, tts.get("lang", "en"))


def _prompted(texts: list[str], tts: dict):
    # CosyVoice 3 (Apache-2.0) or Ming-3.0-tts (MIT), run by <engine>_worker.py in its own environment: every sentence in
    # the voice of tts["prompt"]; an instruction in front ("<instruction><|endofprompt|>...", tags.text_for_tts) sets the emotion
    # Navoiy (Uzbek) is CosyVoice 2 with its own weights: the CosyVoice worker, calm when the sentence has no emotion
    repo, model = {"cosyvoice": (COSYVOICE_REPO, COSYVOICE_MODEL), "navoiy": (COSYVOICE_REPO, NAVOIY_MODEL),
                   "ming": (MING_REPO, MING_MODEL)}[tts["engine"]]
    navoiy = tts["engine"] == "navoiy"
    prompts = tts.get("prompts") or [tts["prompt"]] * len(texts)  # one recording per sentence: several speakers, one load
    with tempfile.TemporaryDirectory() as tmp:
        items = [{"text": t.rpartition(INSTRUCT_END)[2], "instruct": t.rpartition(INSTRUCT_END)[0] or (NAVOIY_CALM if navoiy else ""),
                  "prompt_wav": p, "out": str(Path(tmp) / f"{i}.wav")} for i, (t, p) in enumerate(zip(texts, prompts))]
        worker = Path(__file__).with_name("cosyvoice_worker.py" if navoiy else f"{tts['engine']}_worker.py")
        p = subprocess.run([str(env_py(tts["engine"])), "-I", "-X", "utf8", str(worker)],
                           input=json.dumps({"repo": str(repo), "model": model, "items": items, **({"llm": NAVOIY_LLM} if navoiy else {})}),
                           capture_output=True, text=True, encoding="utf8", errors="replace")
        if p.returncode != 0:
            raise SystemExit(f"{tts['engine']} failed: " + ((p.stderr.strip().splitlines() or ["no output"])[-1]))
        clips = [sf.read(it["out"], dtype="float32") for it in items]
    yield from clips


def word_errors(clips: list[tuple[np.ndarray, int]], texts: list[str], lang: str) -> list[float]:
    """How far off its text Whisper (large-v3) heard each clip: 1 - difflib ratio on the letters (0 = every word)."""
    import torch  # noqa: F401 - loads the CUDA DLLs (cublas) that ctranslate2 needs on Windows
    from faster_whisper import WhisperModel

    dev = device()
    model = WhisperModel("large-v3", device=dev, compute_type="float16" if dev == "cuda" else "int8")
    errs = []
    for (audio, sr), text in zip(clips, texts):
        x = np.interp(np.arange(0, len(audio), sr / 16000), np.arange(len(audio)), audio).astype("float32")
        heard = "".join(s.text for s in model.transcribe(x, language=lang or None, condition_on_previous_text=False)[0])
        errs.append(1 - difflib.SequenceMatcher(None, _letters(text), _letters(heard)).ratio())
    del model
    free_gpu()
    return errs


def _ming(texts: list[str], tts: dict):
    # Ming-3.0-tts speaks; CosyVoice 3 speaks what Ming cannot or should not: an emotion beyond Ming's 7 (its instruction
    # is then CosyVoice's sentence, tags.EMOTIONS) and plain sentences when tts["plain"] is "cosyvoice" (Korean: Whisper found
    # 17 of Ming's 42 TED-Ed sentences off, C36). Then every sentence Whisper hears more than tts["retry_cer"] off is said
    # once more by CosyVoice (CosyVoice varies too: the TED-Ed URL line 4 % off in C35, 34 % in C37) - the better take stays
    split = [t.rpartition(INSTRUCT_END) for t in texts]
    prompts = tts.get("prompts") or [tts["prompt"]] * len(texts)
    some = lambda ids, **kw: {**tts, **kw, "prompts": [prompts[i] for i in ids]}  # noqa: E731 - each sentence keeps its voice
    cosy = COSYVOICE_PY.exists()
    if cosy:
        ming = [i for i, (how, _, _) in enumerate(split) if how in MING_TO_COSY or (not how and tts.get("plain") != "cosyvoice")]
    else:  # no CosyVoice: Ming says everything, without the emotions it does not have
        ming = list(range(len(texts)))
        texts = [t if how in MING_TO_COSY else text for t, (how, _, text) in zip(texts, split)]
    clips = [None] * len(texts)
    if ming:
        for i, clip in zip(ming, _prompted([texts[i] for i in ming], some(ming))):
            clips[i] = clip
    first = [i for i in range(len(texts)) if clips[i] is None]
    if not first and (not cosy or tts.get("retry_cer", .05) >= 1):
        yield from clips
        return
    from math import gcd

    from scipy.signal import resample_poly
    sr = next((c[1] for c in clips if c), 44100)  # Ming's rate: one video / one file keeps one rate

    def by_cosyvoice(ids):
        how = [MING_TO_COSY.get(split[i][0], split[i][0]) for i in ids]
        for i, (audio, r) in zip(ids, _prompted([(h + INSTRUCT_END if h else "") + split[i][2] for i, h in zip(ids, how)],
                                                 some(ids, engine="cosyvoice"))):
            g = gcd(sr, r)
            yield i, (resample_poly(audio, sr // g, r // g).astype("float32"), sr)  # CosyVoice: 24 kHz

    if first:
        for i, c in by_cosyvoice(first):
            clips[i] = c
    lang, limit, better = tts.get("lang", "en"), tts.get("retry_cer", .05), 0
    off = []
    if limit < 1:
        errs = word_errors(clips, [s[2] for s in split], lang)
        off = [i for i, e in enumerate(errs) if e > limit]
        if off:
            again = dict(by_cosyvoice(off))
            for i, e in zip(off, word_errors([again[i] for i in off], [split[i][2] for i in off], lang)):
                if e < errs[i]:  # keep the take Whisper heard better
                    clips[i], better = again[i], better + 1
    print(f"         Ming: {len(texts) - len(first)} by Ming, {len(first)} by CosyVoice (plain or an emotion beyond Ming); "
          f"{len(off)} heard off and said again, the new take better for {better}")
    yield from clips


# one adapter per engine, not per language
ENGINES = {"kokoro": _kokoro, "mms": _mms, "chatterbox": _chatterbox, "chatterbox_ml": _chatterbox, "cosyvoice": _prompted,
           "ming": _ming, "navoiy": _prompted, "piper": _piper}

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
    if tts["engine"] in PROMPTED and not env_py(tts["engine"]).exists():
        tts = {**tts, **tts["fallback"]}  # without its environment: the voices DUBBE had before CosyVoice / Ming
    chosen = data.get("speakers", {}).get(speaker, {}).get("voice")
    clone_py = env_py(tts.get("clone", "")) or CHATTERBOX_PY
    if (chosen or "").startswith(("clone:", "video:")) and prompt and Path(prompt).exists() and clone_py.exists() and "clone" in tts:
        return {**tts, "engine": tts["clone"], "voice": chosen, "prompt": str(prompt)}
    preset = chosen if chosen in tts.get("voices", {}) else tts["voice"]  # no voice chosen yet: the language's default
    if tts["engine"] in PROMPTED:  # these always speak from a recording: here the synthetic preset's (preset_prompt)
        return {**tts, "voice": preset, "prompt": str(preset_prompt(preset))}
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


LEVEL_DB = -22.0  # every sentence's speech at this level (dBFS): about where Ming's clips were on average (C50)


def speech_db(audio: np.ndarray, sr: int) -> float:
    """How loud the speech is: RMS of the 20 ms frames within 30 dB of the loudest one (pauses do not count)."""
    n = max(1, int(.02 * sr))
    if len(audio) < n:
        return -120.0
    f = np.sqrt(np.mean(audio[: len(audio) // n * n].astype("float64").reshape(-1, n) ** 2, axis=1))
    return float(20 * np.log10(np.sqrt(np.mean(f[f >= f.max() / 31.6] ** 2)) + 1e-12))


def level(audio: np.ndarray, sr: int) -> np.ndarray:
    """One loudness for every sentence: the voices came out up to 12 dB apart within one speaker, which sounds like
    another person (project 14, C50). Silence stays silence."""
    db = speech_db(audio, sr)
    return audio if db < -80 else (audio * 10 ** ((LEVEL_DB - db) / 20)).astype(audio.dtype)


def finish(path: Path, audio: np.ndarray, sr: int, tags: list[str], engine: str = "") -> float:
    """Level the sentence, apply the reviewer's delivery tags ([soft], [pause], [slow] ...) and write it; returns its
    length. Emotions the engine acted itself (CosyVoice) are not changed again."""
    sf.write(path, shape_audio(level(audio, sr), sr, dubbe_tags(tags, engine)), sr)
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
    calls: dict = {}  # Ming / CosyVoice speak every speaker in one call (each sentence from its speaker's recording), so
    for sp, its in groups.items():  # their models load once, not once per speaker; other engines: one call per speaker
        tts = tts_cfg(data, cfg, work / f"voice_prompt_{sp}.wav", sp)
        if tts["engine"] not in ENGINES:
            raise SystemExit(f"TTS engine '{tts['engine']}' is not implemented yet (have: {', '.join(ENGINES)})")
        calls.setdefault(tts["engine"] if tts["engine"] in PROMPTED else sp, []).append((sp, tts, its))
    for call in calls.values():
        flat = [(s, t, tts, sp) for sp, tts, its in call for s, t in its]
        texts = [text_for_tts(t, s.get("tags") or [], tts["engine"], tts.get("lang", "")) for s, t, tts, _ in flat]
        first = call[0][1]
        run = {**first, "prompts": [tts["prompt"] for _, _, tts, _ in flat]} if first["engine"] in PROMPTED else first
        run = {**run, "seeds": [s.get("take", 0) for s, _, _, _ in flat]}  # engines with a fixed seed: a retake sounds new
        for (s, _, tts, sp), (audio, sr) in zip(flat, ENGINES[first["engine"]](texts, run)):
            yield s, audio, sr, tts, sp


CLIP_VERSION = 2  # raise when finish() changes how a clip sounds (2: one level, no glide on self-asked questions, C50)


def fingerprint(s: dict, tts: dict) -> str:
    """What a sentence's clip was made from: text, tags, take, voice and DUBBE's clip processing. Same fingerprint: a re-dub
    keeps the clip (C49)."""
    key = [s.get("tgt_text") or "", s.get("tags") or [], s.get("take", 0), tts["engine"], tts["voice"], tts.get("prompt"),
           CLIP_VERSION]
    return hashlib.sha1(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:16]


def run(video: Path, work: Path, cfg: dict) -> None:
    """Speak every sentence whose text, tags, take or voice changed since its clip was made; the others keep their clip,
    so fixing one sentence of a 20-minute video re-speaks one sentence."""
    data = read_json(work / "segments.json")
    segs = data["segments"]
    out_dir = work / "tts"
    out_dir.mkdir(exist_ok=True)
    voices = {sp: tts_cfg(data, cfg, work / f"voice_prompt_{sp}.wav", sp) for sp in {s.get("speaker", "S1") for s in segs}}
    todo = [s for s in segs if s.get("tts_key") != fingerprint(s, voices[s.get("speaker", "S1")])
            or not (out_dir / f"{s['id']}.wav").exists()]
    for s, audio, sr, tts, sp in synth(data, cfg, work, [(s, s["tgt_text"] or "") for s in todo]):
        s["tts_dur"] = finish(out_dir / f"{s['id']}.wav", trim(audio), sr, s.get("tags") or [], tts["engine"])
        s["tags_not_performed"] = not_performed(s.get("tags") or [], tts["engine"])
        s["tts_key"] = fingerprint(s, tts)
    print(f"         spoke {len(todo)} of {len(segs)} sentences (the others are unchanged)")
    data["spoken"] = [s["id"] for s in todo]  # this run's sentences: a library clone's use counts only these (web/worker.py)
    used = {sp: {"engine": t["engine"], "voice": t["voice"]} for sp, t in voices.items()}
    for sp, u in used.items():
        data.setdefault("speakers", {}).setdefault(sp, {})["used"] = u
    data["tts_used"] = used.get("S1") or next(iter(used.values()), {})  # the main speaker's, for older readers
    free_gpu()
    write_json(work / "segments.json", data)
