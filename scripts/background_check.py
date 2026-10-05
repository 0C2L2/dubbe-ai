"""T-12 background check: does a non-speech sound survive dubbing, and does the original voice leak?

    python scripts/background_check.py        # needs data/fleurs_ko_kr.mp4 (scripts/make_fleurs_clip.py)

1. Adds a phone ring (440 + 480 Hz, US ringback tones) to the FLEURS Korean clip in the pauses between sentences.
2. Dubs it ko -> en with background kept.
3. (a) Ring level in the dubbed video vs. the original, measured on the ring's own frequencies.
   (b) Voice leak: Korean Whisper on background.wav - words per minute should be close to 0.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR, RING_DUR = 44100, 0.8
CLIP, REF, OUT = Path("data/fleurs_ko_kr.mp4"), Path("data/fleurs_ko_kr.ref.json"), Path("data/fleurs_ko_ring.mp4")


def ring_db(audio: np.ndarray, t: float) -> float:
    """Power on the ring's two tones in the window [t, t + RING_DUR], in dB."""
    win = audio[int(t * SR):int((t + RING_DUR) * SR)]
    spec = np.abs(np.fft.rfft(win * np.hanning(len(win))))
    freqs = np.fft.rfftfreq(len(win), 1 / SR)
    band = (np.abs(freqs - 440) < 5) | (np.abs(freqs - 480) < 5)
    return 10 * np.log10(np.sum(spec[band] ** 2) + 1e-12)


def audio_of(video: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="float32")


def main() -> None:
    ref = json.loads(REF.read_text(encoding="utf8"))
    times = [r["end"] + 0.1 for r in ref[:-1]][:8]  # inside the 1 s pauses between sentences
    t = np.arange(int(RING_DUR * SR)) / SR
    tone = (0.15 * (np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 480 * t))).astype("float32")
    orig = audio_of(CLIP)
    ring = np.zeros_like(orig)
    for s in times:
        ring[int(s * SR):int(s * SR) + len(tone)] += tone
    sf.write("data/ring.wav", ring, SR)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(CLIP), "-i", "data/ring.wav", "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", str(OUT)], check=True)
    Path("data/ring.wav").unlink()

    subprocess.run(["dubbe", str(OUT), "--src", "ko", "--tgt", "en", "--force"], check=True)
    work = Path("work") / f"{OUT.stem}.ko-en"

    src, dub = audio_of(OUT), audio_of(work / "dubbed.mp4")
    diffs = [ring_db(dub, s) - ring_db(src, s) for s in times]
    print(f"(a) ring level in dub vs original: mean {np.mean(diffs):+.1f} dB, worst {min(diffs):+.1f} dB "
          f"over {len(times)} rings (pass: within -3 dB)")

    import torch  # noqa: F401 - CUDA DLLs for ctranslate2 on Windows
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3-turbo", device="cuda" if torch.cuda.is_available() else "cpu")
    segs, info = model.transcribe(str(work / "background.wav"), language="ko", vad_filter=True)
    text = " ".join(s.text.strip() for s in segs)
    wpm = len(text.split()) / (info.duration / 60)
    print(f"(b) voice leak: {wpm:.1f} Korean words/min recognised in background.wav (pass: <= 1)  {text[:120]!r}")
    sys.exit(0 if min(diffs) >= -3 and wpm <= 1 else 1)


if __name__ == "__main__":
    main()
