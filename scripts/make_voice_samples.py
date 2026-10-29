"""Voice samples for the website's voice pickers: one short sentence per voice in every language, written to
<DUBBE_WEB_DATA>/samples/<name>.wav (tts.sample_name) - the git-ignored data folder, like all audio. English with Kokoro;
every other language with Chatterbox in one run (each voice as its own reference). Samples made before are kept.

    python scripts/make_voice_samples.py
"""
import json
import os
import tempfile
from pathlib import Path

import soundfile as sf
import torch  # noqa: F401  (before kokoro/transformers: Windows CUDA DLLs)
import yaml

import dubbe
from dubbe import config, translate
from dubbe.tts import ENGINES, preset_prompt, sample_name, trim

OUT = Path(os.environ.get("DUBBE_WEB_DATA", "data/web")) / "samples"
EN = "Hi, I'm {name}. DUBBE placed this sentence exactly where the speaker said it."
# into the other languages; no brand name - the translator turned "DUBBE" into 杜比 (Dolby), Дубб, Ντουμπέ ...
SAY = "Hello. This sentence was placed exactly where the speaker said it."
TEXT = {"ko": "안녕하세요. 이 문장은 원래 말한 자리에 정확히 놓였습니다.",
        "ja": "こんにちは。この文は、話し手が言ったちょうどその場所に置かれました。",  # the translator wrote スピーカー (a loudspeaker)
        "zh": "你好。这句话被准确地放在了说话人说出它的位置。"}


def sentences(langs: list[str]) -> dict:
    """The sample sentence in every other language, translated once by DUBBE's own translator (kept in sample_texts.json,
    so reruns say the same)."""
    f = OUT / "sample_texts.json"
    have = {**(json.loads(f.read_text(encoding="utf8")) if f.exists() else {}), **TEXT}  # written by hand wins
    for lang in (x for x in langs if x not in have):
        with tempfile.TemporaryDirectory() as w:
            seg = {"id": 1, "start": 0, "end": 0, "src_text": SAY, "tgt_text": None, "edited": False}
            Path(w, "segments.json").write_text(json.dumps({"segments": [seg]}), encoding="utf8")
            translate.run(None, Path(w), config.load("en", lang))
            have[lang] = json.loads(Path(w, "segments.json").read_text(encoding="utf8"))["segments"][0]["tgt_text"]
    f.write_text(json.dumps(have, ensure_ascii=False, indent=1), encoding="utf8")
    return have


langs = yaml.safe_load((Path(dubbe.__file__).parent / "languages.yaml").read_text(encoding="utf8"))
codes = [k for k in langs if k != "defaults"]
OUT.mkdir(parents=True, exist_ok=True)
say = sentences([c for c in codes if c != "en"])
for lang in codes:
    tts = langs[lang]["tts"]
    todo = [(v, info) for v, info in tts.get("voices", {}).items() if not (OUT / f"{sample_name(v, lang, info)}.wav").exists()]
    if lang == "en":
        made = [next(ENGINES["kokoro"]([EN.format(name=v.split("_")[1].title())], {**tts, "voice": v})) for v, _ in todo]
    else:  # its built-in voice, or an English preset's reference recording (as in tts.tts_cfg)
        run = {**tts, "engine": tts["clone"], "prompts": [str(preset_prompt(v)) if i.get("prompt") else None for v, i in todo]}
        made = list(ENGINES[run["engine"]]([say[lang]] * len(todo), run)) if todo else []
    for (v, info), (audio, sr) in zip(todo, made):
        f = OUT / f"{sample_name(v, lang, info)}.wav"
        sf.write(f, trim(audio), sr)
        print(f, round(len(trim(audio)) / sr, 1), "s", flush=True)
