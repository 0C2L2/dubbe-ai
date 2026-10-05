"""T-14 voice-register check (plan C10): does the pitch-based lower/higher call agree with the speaker
gender recorded in FLEURS (CC BY 4.0)? Used to calibrate `register_split_hz`.

    python scripts/voice_check.py                 # calibrate on ko_kr, test on held-out en_us
    python scripts/voice_check.py ko_kr en_us 40  # calibration lang, test lang, recordings per group

Result 2026-10-06: split 122 Hz -> 95 % on ko_kr (calibration) and 95 % on en_us (held out).
FLEURS gender is only a proxy for voice register; DUBBE itself never labels people by sex.
"""
import csv
import io
import sys
import tarfile

import soundfile as sf
from huggingface_hub import hf_hub_download

from dubbe.voice import median_f0


def pitches(lang: str, n: int) -> dict[str, list[float]]:
    rows = csv.reader(open(hf_hub_download("google/fleurs", f"data/{lang}/dev.tsv", repo_type="dataset"),
                           encoding="utf8"), delimiter="\t", quoting=csv.QUOTE_NONE)
    tar = tarfile.open(hf_hub_download("google/fleurs", f"data/{lang}/audio/dev.tar.gz", repo_type="dataset"))
    members = {m.name.split("/")[-1]: m for m in tar.getmembers()}
    out = {"MALE": [], "FEMALE": []}
    for r in rows:  # columns: id, file_name, raw, transcription, phonemes, num_samples, gender
        if r[6] in out and len(out[r[6]]) < n and r[1] in members:
            out[r[6]].append(median_f0(*sf.read(io.BytesIO(tar.extractfile(members[r[1]]).read()), dtype="float32")))
    return out


def accuracy(p: dict, split: float) -> float:
    return (sum(v < split for v in p["MALE"]) + sum(v >= split for v in p["FEMALE"])) / (len(p["MALE"]) + len(p["FEMALE"]))


def main() -> None:
    cal, test, n = (sys.argv[1:3] + ["ko_kr", "en_us"][len(sys.argv[1:3]):]) + [int(sys.argv[3]) if len(sys.argv) > 3 else 40]
    pc = pitches(cal, n)
    split = max(range(90, 200, 2), key=lambda t: accuracy(pc, t))
    print(f"{cal} (calibration): best split {split} Hz -> {accuracy(pc, split):.0%}")
    print(f"{test} (held out):   split {split} Hz -> {accuracy(pitches(test, n), split):.0%}")


if __name__ == "__main__":
    main()
