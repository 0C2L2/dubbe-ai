"""Delivery tags a reviewer can put on a sentence, e.g. [whisper] or [laugh].

Two kinds:
- DELIVERY tags are applied by DUBBE itself to the finished audio, so they work with every voice and language.
  Measured 2026-10-15: no engine raises the pitch for a "?" reliably (end of sentence vs. middle, 3 sentences:
  Kokoro rose in 0, MMS Korean in 0, Chatterbox in 2) and Chatterbox's [whispering] is not a real whisper, so
  [question], [whisper] and the emotions are made here: pitch, speed, loudness and breath - not acted emotion.
- VOCAL tags are sounds only the voice engine can make, as the engine's own token in the text
  (VOCAL_TOKENS). Kokoro and MMS have none; tags an engine cannot do are recorded as
  "not performed" in segments.json and the report instead of being silently dropped.
"""
import numpy as np
from scipy.linalg import solve_toeplitz
from scipy.signal import lfilter

from .korean import read_numbers

DELIVERY = {"slow": "speak slower", "fast": "speak faster", "soft": "quieter", "loud": "louder",
            "pause": "short pause before the line", "question": "pitch rises at the end", "whisper": "breathy whisper",
            "excited": "higher, faster, a bit louder", "sad": "lower, slower, quieter", "angry": "louder, a bit higher and faster"}
VOCAL = ["laugh", "sigh", "gasp", "cough"]
ALL = list(DELIVERY) + VOCAL

# vocal tag -> the engine's token (Chatterbox Turbo's added_tokens.json). An AudioSet classifier heard the sound on
# 3 sentences each: cough 0.37, gasp 0.17, laugh 0.11, sigh 0.08 (plain speech ~0.00) - weak but there. Chatterbox
# Multilingual has [laughter] [sigh] [gasp] [cough] in its vocabulary but made none of them in Korean (all 0.00), so
# Korean has no tokens: those tags are reported "not performed" (test-results C19d).
VOCAL_TOKENS = {"chatterbox": {"laugh": "[laugh]", "sigh": "[sigh]", "gasp": "[gasp]", "cough": "[cough]"}}

SPEED = {"slow": 0.85, "fast": 1.15}
GAIN_DB = {"soft": -6.0, "loud": 4.0, "whisper": -3.0, "excited": 2.0, "sad": -3.0, "angry": 5.0}
RATE = {"excited": 1.12, "sad": 0.9, "angry": 1.05}  # played faster/slower like a tape: 1.12 = 2 semitones up, 11 % shorter
RISE_ST = 8  # [question]: the end glides up towards this many semitones. Korean, 12 sentences: Whisper heard a question
             # in 4 (no glide), 5 (5 st), 7 (8 st), 7 (11 st). Kokoro's last-syllable drop (~5 st in 150 ms) beats any glide.
PAUSE_S = 0.5


def text_for_tts(text: str, tags: list[str], engine: str = "", lang: str = "") -> str:
    """[question]: end the sentence with '?' (some voices also rise by themselves).
    Vocal tags the engine can perform go in front as its tokens, e.g. "[laugh] That's funny.".
    Korean digits are written out in words (the voices misread them)."""
    if lang == "ko":
        text = read_numbers(text)
    if "question" in tags and not text.rstrip().endswith("?"):
        text = text.rstrip().rstrip(".!") + "?"
    tokens = VOCAL_TOKENS.get(engine, {})
    return " ".join([tokens[t] for t in tags if t in tokens] + [text])


def speed(tags: list[str]) -> float:
    return SPEED.get(next((t for t in tags if t in SPEED), ""), 1.0)


def _rate(audio: np.ndarray, rate: float) -> np.ndarray:
    return np.interp(np.arange(0, len(audio) - 1, rate), np.arange(len(audio)), audio) if len(audio) > 1 else audio


def _rise(audio: np.ndarray, sr: int) -> np.ndarray:
    """The last 35 % (at most 0.8 s) is read faster and faster, so the pitch glides up like a question."""
    n = min(int(len(audio) * .35), int(.8 * sr))
    pos = np.cumsum(2 ** (np.linspace(0, RISE_ST, n) / 12)) - 1
    return np.concatenate([audio[:-n], np.interp(pos[pos <= n - 1], np.arange(n), audio[-n:])]) if n > 1 else audio


def _whisper(audio: np.ndarray, sr: int) -> np.ndarray:
    """Keep the mouth shapes (an LPC filter per 32 ms frame) but replace the buzz of the vocal cords with noise."""
    n, order = int(.032 * sr), sr // 1000 + 2
    pre = np.append(audio[:1], audio[1:] - .97 * audio[:-1])  # brighter: a whisper has little bass
    noise = np.random.default_rng(0).standard_normal(len(audio) + n)
    out, win = np.zeros(len(audio) + n), np.hanning(n)
    for i in range(0, len(audio), n // 2):
        x, f = (np.pad(s[i:i + n], (0, n - len(s[i:i + n]))) * win for s in (audio, pre))
        r = np.correlate(f, f, "full")[n - 1:n + order]
        if r[0] < 1e-9:
            continue
        a = solve_toeplitz(np.r_[r[0] * 1.0001, r[1:order]], -r[1:order + 1])
        y = lfilter([1.0], np.r_[1.0, a], noise[i:i + n] * win)
        out[i:i + n] += y * np.sqrt((x @ x) / (y @ y + 1e-12))  # as loud as the voiced frame
    return out[:len(audio)]


def shape_audio(audio: np.ndarray, sr: int, tags: list[str]) -> np.ndarray:
    """Whisper, pitch for the emotions and [question], level, then [pause] in front. (Speed is applied with ffmpeg.)"""
    dtype = audio.dtype
    if "whisper" in tags:
        audio = _whisper(audio, sr)
    for t in tags:
        if t in RATE:
            audio = _rate(audio, RATE[t])
    if "question" in tags:
        audio = _rise(audio, sr)
    for t in tags:
        if t in GAIN_DB:
            audio = audio * 10 ** (GAIN_DB[t] / 20)
    peak = np.abs(audio).max(initial=0)
    if peak > .99:
        audio = audio * (.99 / peak)  # louder, but never clipped
    if "pause" in tags:
        audio = np.concatenate([np.zeros(int(PAUSE_S * sr)), audio])
    return audio.astype(dtype)


def not_performed(tags: list[str], engine: str) -> list[str]:
    return [t for t in tags if t in VOCAL and t not in VOCAL_TOKENS.get(engine, {})]
