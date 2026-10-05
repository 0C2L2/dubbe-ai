from pathlib import Path

import yaml

REQUIRED = ("whisper", "nllb", "sentence_end", "tts")


def load(src: str, tgt: str) -> dict:
    langs = yaml.safe_load((Path(__file__).parent / "languages.yaml").read_text(encoding="utf8"))
    defaults = langs.pop("defaults")
    for code in (src, tgt):
        if code not in langs:
            raise SystemExit(f"Language '{code}' is not in languages.yaml (have: {', '.join(langs)})")
        missing = [k for k in REQUIRED if k not in langs[code]]
        if missing:
            raise SystemExit(f"languages.yaml entry '{code}' is missing: {', '.join(missing)}")
    return {**defaults, "src": {"code": src, **langs[src]}, "tgt": {"code": tgt, **langs[tgt]}}
