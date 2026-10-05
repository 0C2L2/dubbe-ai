from pathlib import Path

from . import ffmpeg


def run(video: Path, work: Path, cfg: dict) -> None:
    # 16 kHz mono PCM is what Whisper expects
    ffmpeg("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(work / "audio.wav"))
    if cfg["keep_background"]:  # full quality for source separation
        ffmpeg("-i", str(video), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(work / "original.wav"))
