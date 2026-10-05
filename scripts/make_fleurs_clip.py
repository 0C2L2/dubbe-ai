"""Build a test video from FLEURS read speech (CC BY 4.0) with reference transcripts and translations.

    python scripts/make_fleurs_clip.py --src ko_kr --tgt en_us --n 12

Writes data/fleurs_<src>.mp4 and data/fleurs_<src>.ref.json ([{start, end, src, tgt}]).
Uses the dev split; the test split is kept for the formal benchmark.
"""
import argparse
import csv
import io
import json
import subprocess
import tarfile
import textwrap
from pathlib import Path

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download

SR, PAUSE = 16000, 1.0


def rows(lang: str) -> dict:
    path = hf_hub_download("google/fleurs", f"data/{lang}/dev.tsv", repo_type="dataset")
    # columns: id, file_name, raw_transcription, transcription, phonemes, num_samples, gender
    out = {}
    for r in csv.reader(open(path, encoding="utf8"), delimiter="\t", quoting=csv.QUOTE_NONE):
        out.setdefault(r[0], r)  # several speakers read the same sentence: keep the first
    return out


def slides(ref: list[dict], folder: Path, font: str) -> Path:
    """Write an ffmpeg filter that shows each sentence like a lecture slide while it is spoken:
    source text large, reference translation small. Returns the filter file path."""
    folder.mkdir(parents=True, exist_ok=True)
    font = font.replace("\\", "/").replace(":", "\\:")  # ffmpeg filter syntax: escape the drive-letter colon
    parts = []
    for n, r in enumerate(ref, 1):
        end = ref[n]["start"] if n < len(ref) else r["end"] + PAUSE
        on = f"enable='between(t,{r['start']},{end})'"
        # source block from the top, reference block anchored to the bottom, so they never overlap
        for kind, text, width, size, color, y in (("src", r["src"], 30, 38, "white", "110"),
                                                  ("tgt", "Reference translation: " + r["tgt"], 80, 22, "0x9aa4b2", "h-text_h-50")):
            f = folder / f"{n}.{kind}.txt"
            f.write_text("\n".join(textwrap.wrap(text, width)), encoding="utf8")
            parts.append(f"drawtext=fontfile='{font}':textfile='{f.as_posix()}':fontsize={size}:fontcolor={color}"
                         f":line_spacing=-{size // 2}:x=(w-text_w)/2:y={y}:{on}")
        parts.append(f"drawtext=fontfile='{font}':text='FLEURS sample  {n}/{len(ref)}':fontsize=20"
                     f":fontcolor=0x5c6878:x=40:y=30:{on}")
    filt = folder / "filter.txt"
    filt.write_text(",\n".join(parts), encoding="utf8")
    return filt


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--font", default="C:/Windows/Fonts/malgun.ttf", help="a font with the source script (Hangul)")
    p.add_argument("--src", default="ko_kr")
    p.add_argument("--tgt", default="en_us")
    p.add_argument("--n", type=int, default=12, help="number of sentences")
    a = p.parse_args()

    src, tgt = rows(a.src), rows(a.tgt)
    ids = [i for i in src if i in tgt][: a.n]
    tar = tarfile.open(hf_hub_download("google/fleurs", f"data/{a.src}/audio/dev.tar.gz", repo_type="dataset"))
    members = {Path(m.name).name: m for m in tar.getmembers()}

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    parts, ref, t = [], [], 0.0
    for i in ids:
        audio, sr = sf.read(io.BytesIO(tar.extractfile(members[src[i][1]]).read()), dtype="float32")
        assert sr == SR
        parts += [audio, np.zeros(int(PAUSE * SR), dtype="float32")]
        ref.append({"start": round(t, 3), "end": round(t + len(audio) / SR, 3), "src": src[i][2], "tgt": tgt[i][2]})
        t += len(audio) / SR + PAUSE

    wav = out_dir / f"fleurs_{a.src}.wav"
    sf.write(wav, np.concatenate(parts), SR)
    mp4 = out_dir / f"fleurs_{a.src}.mp4"
    filt = slides(ref, out_dir / "slides", a.font)
    # ffmpeg >= 7: "-/vf file" reads the filter graph from a file (avoids quoting Korean text on the command line)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x10151f:s=1280x720:r=25:d={t:.2f}",
                    "-i", str(wav), "-/vf", str(filt), "-c:v", "libx264", "-c:a", "aac", "-shortest", str(mp4)], check=True)
    wav.unlink()
    (out_dir / f"fleurs_{a.src}.ref.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"{mp4}: {len(ids)} sentences, {t:.1f} s")


if __name__ == "__main__":
    main()
