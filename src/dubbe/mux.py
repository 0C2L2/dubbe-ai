import subprocess
from pathlib import Path

from . import ffmpeg, read_json, video_duration

# Background under the new voice: duck it (sidechain compression keyed by the dub voice) only while
# the dub speaks, so sounds between lines (a phone ringing, music) keep their original level.
# highpass 40 Hz removes DC offset and the 43 Hz hum Demucs leaves; the gate mutes residue hiss below -50 dB.
DUCK = ("[1:a]aresample=44100,aformat=channel_layouts=stereo,asplit=2[v1][v2];"
        "{bg}aformat=channel_layouts=stereo,highpass=f=40,agate=threshold=0.003:ratio=4:attack=5:release=250[bg];"
        "[bg][v1]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck];"
        "[duck][v2]amix=inputs=2:normalize=0:duration=longest[a]")


def pieces(segs: list[dict], total: float) -> list[tuple[float, float, float]]:
    """Source time ranges with their slow-down factor; neighbouring unslowed ranges are merged."""
    ranges = [(0.0, segs[0]["start"], 1.0)] if segs else [(0.0, total, 1.0)]
    for i, s in enumerate(segs):
        ranges.append((s["start"], segs[i + 1]["start"] if i + 1 < len(segs) else total, s.get("slow", 1.0)))
    out = []
    for a, b, f in ranges:
        if b - a <= 0.001:
            continue
        if out and out[-1][2] == f == 1.0:
            out[-1] = (out[-1][0], b, 1.0)
        else:
            out.append((a, b, f))
    return out


def _retime(pcs: list[tuple], fps: str, bg: bool) -> str:
    """Filter that slows the picture (and the background with it) piece by piece."""
    n = len(pcs)
    f = f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n)) + ";"
    f += "".join(f"[s{i}]trim=start={a}:end={b},setpts=(PTS-STARTPTS)*{k}[v{i}];" for i, (a, b, k) in enumerate(pcs))
    f += "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,fps={fps}[vout]"
    if bg:
        f += f";[2:a]asplit={n}" + "".join(f"[t{i}]" for i in range(n)) + ";"
        f += "".join(f"[t{i}]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,atempo={1 / k:.5f}[b{i}];"
                     for i, (a, b, k) in enumerate(pcs))
        f += "".join(f"[b{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[bgr]"
    return f


def run(video: Path, work: Path, cfg: dict) -> None:
    out, bg = str(work / "dubbed.mp4"), work / "background.wav"
    inputs = ["-i", str(video), "-i", str(work / "dub.wav")] + (["-i", str(bg)] if bg.exists() else [])
    segs = read_json(work / "segments.json")["segments"]

    if any(s.get("slow", 1.0) > 1.0 for s in segs):  # picture is slowed somewhere: re-render video
        fps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=r_frame_rate", "-of", "csv=p=0", str(video)],
                             check=True, capture_output=True, text=True).stdout.strip()
        graph = _retime(pieces(segs, video_duration(video)), fps, bg.exists())
        graph += ";" + DUCK.format(bg="[bgr]") if bg.exists() else ""
        video_args = ["-map", "[vout]", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
        ffmpeg(*inputs, "-filter_complex", graph, *video_args, "-map", "[a]" if bg.exists() else "1:a",
               "-c:a", "aac", "-b:a", "192k", "-shortest", out)
    elif bg.exists():
        ffmpeg(*inputs, "-filter_complex", DUCK.format(bg="[2:a]"),
               "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out)
    else:  # voice only: copy the picture as-is, replace the sound with the dub track
        ffmpeg(*inputs, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", out)
