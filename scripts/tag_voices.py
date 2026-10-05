"""Measure the pitch of each preset TTS voice for voice matching (plan C10, step 2).

    python scripts/tag_voices.py en      # prints a `voices:` table to paste into languages.yaml

Every voice says the same sentence; its median pitch is measured with the same function used on
speakers (dubbe.voice.median_f0), so speaker-vs-voice comparisons are like for like.
"""
import sys

import numpy as np
from huggingface_hub import list_repo_files

from dubbe.config import load
from dubbe.tts import ENGINES
from dubbe.voice import median_f0

SENTENCE = {"en": "Today we will look at how attention works, and why it changes over time.",
            "ko": "오늘은 주의력이 어떻게 작동하는지, 그리고 왜 시간이 지나면서 변하는지 살펴보겠습니다."}


def main() -> None:
    lang = sys.argv[1]
    tts = load(lang, lang)["tgt"]["tts"]
    if tts["engine"] == "kokoro":  # all presets for this language: voice ids start with the language letter
        prefixes = {"en": ("af_", "am_", "bf_", "bm_")}[lang]
        voices = sorted(f.split("/")[-1][:-3] for f in list_repo_files("hexgrad/Kokoro-82M")
                        if f.startswith("voices/") and f.split("/")[-1].startswith(prefixes))
    else:
        voices = [tts["voice"]]
    print("  voices:  # median pitch (Hz) measured by scripts/tag_voices.py")
    for v in voices:
        audio, sr = next(ENGINES[tts["engine"]]([SENTENCE[lang]], {**tts, "voice": v}))
        reg = {"f": "higher", "m": "lower"}.get(v[1], "?") if tts["engine"] == "kokoro" else "?"  # preset's own label
        print(f"      {v}: {{f0: {median_f0(np.asarray(audio, dtype='float32'), sr):.0f}, register: {reg}}}")


if __name__ == "__main__":
    main()
