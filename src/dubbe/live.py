"""Live dubbing (beta): a live stream dubbed into English, Kazakh, Korean or Uzbek, watched DELAY seconds behind it (C52-C54).

ffmpeg reads the stream once. The picture and the original sound go out unchanged as a growing HLS stream (video.m3u8,
not re-encoded); the same sound also comes here, where it is cut into pieces of about PIECE seconds at a pause and each
piece is dubbed with the models kept loaded: Demucs (background) -> Whisper -> NLLB -> Kokoro -> fit and mix. Each piece
is written as p<n>.wav with its start time in pieces.json; the page plays the video muted and the pieces on the video's
clock, so the dub can never drift from the picture. Measured on this laptop: 2.3-2.8x faster than real time; a delay of
about 27 s is needed with 10-s pieces (C52).

Beta limits: one fast voice for everyone (TARGETS), no review (mistakes reach the viewer), at most MAX_MINUTES per session,
one session at a time (it holds the GPU).

usage (test, a file played as if live): python -m dubbe.live <out dir> <spoken language> <file> [voice]
"""
import json
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from . import config, device

PIECE, MOST = 10.0, 20.0  # a piece ends at the first pause after PIECE s, at most MOST s (C52)
DELAY = 30                # seconds the viewer watches behind the stream: 27 s were needed with 10-s pieces (C52)
LATE, MAX_STRETCH = 1.0, 1.3
MAX_MINUTES = 30
SR, OUT_SR = 44100, 32000  # the stream's sound; the dub pieces (stereo, 16 bit: ~1 Mbit/s)
BLOCK = SR * 4 // 4        # bytes per read: 0.25 s of 16-bit stereo


def cut(speech: list[tuple[float, float]], length: float, piece: float = PIECE, most: float = MOST) -> float | None:
    """Where a piece ends, in seconds of the audio heard so far (`length`, speech spans from the VAD): the middle of the
    first pause after `piece` seconds (a word is never cut), or just after the last speech once the speaker has stopped,
    or `most` seconds. None: wait for more audio."""
    ends = [(e + s1) / 2 for (_, e), (s1, _) in zip(speech, speech[1:])]
    if speech and length - speech[-1][1] >= .3:
        ends.append(min(speech[-1][1] + .15, length))  # the speaker has stopped (the next words not heard yet)
    if not speech:
        ends.append(length)  # nothing said: music or silence
    at = next((x for x in ends if x >= piece), None)
    return min(at, most) if at is not None else most if length >= most else None


def resolve(url: str) -> tuple[list[tuple[str, dict]], bool]:
    """The media behind a link (yt-dlp: YouTube and most sites, or a direct .m3u8 / .mp4): one stream with picture and
    sound, or - as YouTube serves live streams - a picture stream and a sound stream (they start within milliseconds of
    each other: 3.5 ms on a YouTube live, C55), each with the HTTP headers the site wants; and whether it is live.
    At most 480p: the picture is passed through as it is."""
    from yt_dlp import YoutubeDL
    with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                    "format": "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b"}) as y:
        info = y.extract_info(url, download=False)
    parts = info.get("requested_formats") or [info]
    media = [(f.get("url") or "", f.get("http_headers") or info.get("http_headers") or {}) for f in parts]
    if not all(m.startswith(("http://", "https://")) for m, _ in media):
        raise ValueError("no stream with picture and sound at this link")
    return media, bool(info.get("is_live"))


def ffmpeg_cmd(media: list[tuple[str, dict]], is_live: bool, live: Path, local: bool = False) -> list[str]:
    """One ffmpeg for the stream (one input, or a picture input and a sound input): the picture copied and the sound
    (started at 0, so both clocks agree) into a growing HLS stream, and the same sound as raw 16-bit stereo on stdout
    for the dubbing."""
    inputs = []
    for url, headers in media:
        head = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        inputs += ["-protocol_whitelist", ("file," if local else "") + "http,https,tls,tcp,crypto",
                   *(["-headers", head] if head else []), *([] if is_live else ["-re"]), "-t", str(MAX_MINUTES * 60), "-i", url]
    a = len(media) - 1  # the sound: the last input
    return ["ffmpeg", "-loglevel", "error", *inputs,
            "-filter_complex", f"[{a}:a:0]aresample={SR}:async=1:first_pts=0,asplit=2[ah][ap]",
            "-map", "0:v:0?", "-map", "[ah]", "-c:v", "copy", "-c:a", "aac", "-b:a", "64k",
            "-f", "hls", "-hls_time", "2", "-hls_list_size", "0", "-hls_playlist_type", "event",
            "-hls_segment_filename", str(live / "v%05d.ts"), str(live / "video.m3u8"),
            "-map", "[ap]", "-ac", "2", "-f", "s16le", "pipe:1"]


class Reader(threading.Thread):
    """Reads ffmpeg's sound all the time, so ffmpeg (and the picture it writes) never waits for the dubbing."""

    def __init__(self, pipe):
        super().__init__(daemon=True)
        self.pipe, self.parts, self.lock, self.done = pipe, [], threading.Lock(), False

    def run(self):
        while data := self.pipe.read(BLOCK):
            with self.lock:
                self.parts.append(data)
        self.done = True

    def take(self) -> bytes:
        with self.lock:
            data, self.parts = b"".join(self.parts), []
        return data


# the fast voice of each language live mode can dub into (the good offline voices are ~3x slower than real time, C49):
# engine, default voice. Kazakh speaks with its offline voice; Korean and Uzbek with the MMS fallbacks (flat, CC BY-NC)
TARGETS = {"en": ("kokoro", "af_heart"), "kk": ("piper", "issai-0"), "ko": ("mms", "facebook/mms-tts-kor"),
           "uz": ("mms", "facebook/mms-tts-uzb-script_cyrillic")}


def voices(tgt: str) -> list[str]:
    """The voices a live dub into `tgt` can use (the first is the default)."""
    engine, default = TARGETS[tgt]
    if engine == "mms":
        return [default]  # one MMS voice per language
    return [default] + [v for v in (config.load("en" if tgt != "en" else "ko", tgt)["tgt"]["tts"].get("voices") or {})
                        if v != default and (engine != "kokoro" or v[:1] in "ab")]


class Dubber:
    """The models, loaded once for the whole stream (29 s on this laptop)."""

    def __init__(self, src: str, voice: str = "", tgt: str = "en"):
        import ctranslate2
        from demucs.pretrained import get_model
        from faster_whisper import WhisperModel
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer

        from .asr import whisper_model
        from .translate import MODEL, TOKENIZER
        self.cfg, self.tgt = config.load(src, tgt), tgt
        dev = self.dev = device()
        asr = self.cfg["src"].get("asr_model", "large-v3-turbo")
        asr = "large-v3-turbo" if asr == "large-v3" else asr  # large-v3 does not fit next to NLLB on 8 GB (C52)
        self.demucs = get_model("htdemucs")
        self.whisper = WhisperModel(whisper_model(asr), device=dev, compute_type="float16" if dev == "cuda" else "int8")
        self.tok = AutoTokenizer.from_pretrained(TOKENIZER, src_lang=self.cfg["src"]["nllb"])
        self.nllb = ctranslate2.Translator(snapshot_download(MODEL), device=dev,
                                           compute_type="int8_float16" if dev == "cuda" else "int8")
        self.engine = TARGETS[tgt][0]
        self.voice = voice if voice in voices(tgt) else TARGETS[tgt][1]
        self.say = self._voice()

    def _voice(self):
        """say(text) -> (audio, sample rate) with the target's fast voice, loaded once."""
        if self.engine == "kokoro":
            from kokoro import KPipeline
            pipe = KPipeline(lang_code=self.voice[0])
            return lambda text: (np.concatenate([np.asarray(a) for _, _, a in pipe(text, voice=self.voice, speed=1.0)]), 24000)
        if self.engine == "piper":  # CPU (MIT; Kazakh voice kk_KZ-issai-high, CC BY 4.0)
            from huggingface_hub import hf_hub_download
            from piper import PiperVoice, SynthesisConfig
            model = self.cfg["tgt"]["tts"]["model"]
            hf_hub_download("rhasspy/piper-voices", model + ".onnx.json")
            pv = PiperVoice.load(hf_hub_download("rhasspy/piper-voices", model + ".onnx"))
            syn = SynthesisConfig(speaker_id=int(self.voice.rsplit("-", 1)[1]))
            return lambda text: (np.concatenate([c.audio_float_array for c in pv.synthesize(text, syn_config=syn)] or
                                                [np.zeros(1, "float32")]), pv.config.sample_rate)
        import torch  # MMS (VITS), one model per language
        from transformers import AutoTokenizer, VitsModel

        from .tts import romanizer
        tok, model = AutoTokenizer.from_pretrained(self.voice), VitsModel.from_pretrained(self.voice).to(self.dev)
        roman = romanizer(tok)

        def say(text):
            ids = tok(roman(text), return_tensors="pt").to(self.dev)
            if ids["input_ids"].shape[1] == 0:
                return np.zeros(1, "float32"), model.config.sampling_rate
            torch.manual_seed(0)
            with torch.no_grad():
                return model(**ids).waveform[0].cpu().numpy(), model.config.sampling_rate
        return say

    def background(self, x: np.ndarray) -> np.ndarray:
        import torch
        from demucs.apply import apply_model
        t = torch.from_numpy(x.T.copy())[None]
        mean, std = t.mean(), t.std() + 1e-8
        random.seed(0)
        with torch.no_grad():
            o = apply_model(self.demucs, (t - mean) / std, device=self.dev, progress=False)[0] * std + mean
        bg = (o.sum(0) - o[self.demucs.sources.index("vocals")]).cpu().numpy().T
        del o, t
        if self.dev == "cuda":
            torch.cuda.empty_cache()  # Demucs keeps its working memory; NLLB (CTranslate2) needs it (C52)
        return bg

    def piece(self, x: np.ndarray, carry: np.ndarray) -> tuple[np.ndarray, list[dict], np.ndarray]:
        """One piece of the stream (44.1 kHz stereo) -> its dubbed sound (same length), what was said and its
        translation (times in the piece), and the end of a sentence that runs into the next piece."""
        from math import gcd

        from .tags import text_for_tts
        from .tts import level, trim
        n = len(x)
        out = self.background(x) if n > SR // 10 else np.zeros_like(x)
        out[:min(len(carry), n)] += carry[:n]
        x16 = resample_poly(x.mean(axis=1), 160, 441).astype("float32")
        segs, _ = self.whisper.transcribe(x16, language=self.cfg["src"]["whisper"], condition_on_previous_text=False,
                                          vad_filter=True)
        said = [(s.start, s.text.strip()) for s in segs if s.text.strip()]
        src = [self.tok.convert_ids_to_tokens(self.tok.encode(t)) for _, t in said]
        res = self.nllb.translate_batch(src, target_prefix=[[self.cfg["tgt"]["nllb"]]] * len(src), beam_size=8,
                                        max_batch_size=4) if src else []
        en = [self.tok.decode(self.tok.convert_tokens_to_ids(r.hypotheses[0][1:]), skip_special_tokens=True).strip() for r in res]
        tail = np.zeros((0, 2), "float32")
        for k, ((t0, _), text) in enumerate(zip(said, en)):
            if not text:
                continue
            c, vsr = self.say(text_for_tts(text, [], self.engine, self.tgt))  # numbers as words; Cyrillic for MMS Uzbek
            c = level(trim(np.asarray(c, "float32")), vsr)
            slot = (said[k + 1][0] if k + 1 < len(said) else n / SR + LATE) - t0
            rate = min(MAX_STRETCH, len(c) / vsr / max(slot, .1))
            if rate > 1.01:
                c = faster(c, rate, vsr)
            g = gcd(SR, vsr)
            c = resample_poly(c, SR // g, vsr // g).astype("float32")[:, None]  # the voice's rate -> 44.1 kHz
            p0 = int(t0 * SR)
            inside = max(0, min(len(c), n - p0))
            out[p0:p0 + inside] += c[:inside]
            if inside < len(c):  # runs into the next piece (at most LATE seconds, more only if it was too long even sped up)
                rest = c[inside:]
                tail = np.pad(tail, ((0, max(0, len(rest) - len(tail))), (0, 0)))
                tail[:len(rest)] += rest
        return out, [{"t": round(t0, 2), "src": s, "tgt": e} for (t0, s), e in zip(said, en)], tail


def faster(audio: np.ndarray, rate: float, sr: int) -> np.ndarray:
    """Speed speech up without raising its pitch (ffmpeg atempo)."""
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
                        "-filter:a", f"atempo={rate:.3f}", "-f", "f32le", "pipe:1"],
                       input=audio.astype("<f4").tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, "<f4")


def save(live: Path, man: dict) -> None:
    """pieces.json for the page, replaced in one step (the page may be reading the old one: retry briefly)."""
    tmp = live / "pieces.tmp"
    tmp.write_text(json.dumps(man, ensure_ascii=False), encoding="utf8")
    for _ in range(20):
        try:
            os.replace(tmp, live / "pieces.json")
            return
        except PermissionError:  # Windows: the file is open for the page right now
            time.sleep(.05)


def speech(buf: np.ndarray) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    x16 = resample_poly(buf.mean(axis=1), 160, 441).astype("float32")
    return [(s["start"] / 16000, s["end"] / 16000) for s in get_speech_timestamps(x16, VadOptions(min_silence_duration_ms=300))]


def run(out: Path, url: str, src: str, voice: str = "", local: bool = False, tgt: str = "en") -> dict:
    """Dub the stream at `url` into `tgt` until it ends, MAX_MINUTES pass, or out/live/stop appears (the Stop button)."""
    live = out / "live"
    live.mkdir(parents=True, exist_ok=True)
    man = {"state": "starting", "delay": DELAY, "pieces": []}
    save(live, man)
    proc, pos, n = None, 0.0, 0
    try:
        media, is_live = ([(url, {})], False) if local else resolve(url)
        dub = Dubber(src, voice, tgt)
        with open(live / "ffmpeg.log", "wb") as log:
            proc = subprocess.Popen(ffmpeg_cmd(media, is_live, live, local), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=log)
        reader = Reader(proc.stdout)
        reader.start()
        man.update(state="live", is_live=is_live)
        save(live, man)
        buf, rest, carry = np.zeros((0, 2), "float32"), b"", np.zeros((0, 2), "float32")
        while True:
            if (live / "stop").exists():
                proc.stdin.write(b"q")  # ffmpeg ends the HLS stream properly
                proc.stdin.flush()
                break
            data = rest + reader.take()
            whole = len(data) // 4 * 4
            rest = data[whole:]
            if whole:
                buf = np.concatenate([buf, np.frombuffer(data[:whole], "<i2").reshape(-1, 2).astype("float32") / 32768])
            ended = reader.done and not reader.parts
            length = len(buf) / SR
            at = length if ended else cut(speech(buf), length) if length >= PIECE else None
            if not at or at < .05:
                if ended:
                    break
                time.sleep(.2)
                continue
            k = int(at * SR)
            started = time.perf_counter()
            audio, lines, carry = dub.piece(buf[:k], carry)
            name = f"p{n:05d}.wav"
            sf.write(live / name, np.clip(resample_poly(audio, 320, 441), -1, 1), OUT_SR, subtype="PCM_16")
            man["pieces"].append({"t": round(pos, 3), "d": round(k / SR, 3), "f": name, "work": round(time.perf_counter() - started, 2),
                                  "lines": [{**ln, "t": round(pos + ln["t"], 2)} for ln in lines]})
            save(live, man)
            print(f"piece {n} {pos:.1f}-{pos + k / SR:.1f} s: {len(lines)} lines, {man['pieces'][-1]['work']} s", flush=True)
            buf, pos, n = buf[k:], pos + k / SR, n + 1
        man["state"] = "ended"
    except Exception as e:
        man.update(state="failed", error=str(e)[:300])
        raise
    finally:
        if proc and proc.poll() is None:
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.terminate()
        save(live, man)
    return {"seconds": round(pos, 1), "pieces": n}


if __name__ == "__main__":  # python -m dubbe.live <out dir> <spoken language> <dub language> <file> [voice]
    a = sys.argv[1:]
    print(json.dumps(run(Path(a[0]), a[3], a[1], a[4] if len(a) > 4 else "", local=True, tgt=a[2])))
