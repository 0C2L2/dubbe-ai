import json
import subprocess
from pathlib import Path


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def write_json(path: Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf8")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def video_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def db(x) -> float:
    import numpy as np
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)) if len(x) else -180.0


def device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def free_gpu() -> None:
    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
