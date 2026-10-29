"""The single tools next to dubbing - text to speech, speech to text, speaker detection, subtitles, translation, voice
isolation. The worker runs each task in its own process like a dub (python -m dubbe.web.tools <task id>), and every tool
reuses the pipeline stages unchanged. Results go to data/web/tasks/<id>/ and the task row."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

from .. import config, ffmpeg, read_json, tags, write_json
from ..report import CAPTION_COLORS, ass, flags, speaker_colors, subtitles, transcript
from . import db

LANGS = yaml.safe_load((Path(__file__).parent.parent / "languages.yaml").read_text(encoding="utf8"))
TAG = re.compile(r"\[([a-z]+)\]")


def folder(tid: int) -> Path:
    return db.ROOT / "tasks" / str(tid)


def media(tid: int) -> Path | None:
    return next((f for f in folder(tid).glob("input.*") if f.is_file()), None)


def split_sentences(text: str) -> list[str]:
    """Split after . ! ? - also when a tag follows with no space ("What?[slow] Are you ...") - and at line breaks."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s*(?=\[)|(?<=[.!?])\s+|\n+", text) if s.strip()]


def parse_tags(sentence: str) -> tuple[str, list[str], list[str]]:
    """'[slow] Hello there [laugh]' -> ('Hello there', ['slow', 'laugh'], []); a tag anywhere applies to its sentence."""
    found = TAG.findall(sentence)
    text = re.sub(r"\s{2,}", " ", TAG.sub(" ", sentence)).strip()
    return text, [t for t in tags.ALL if t in found], [t for t in found if t not in tags.ALL]


def sentences(text: str) -> list[tuple[str, list[str], list[str]]]:
    """Sentences with their tags. Tags standing on their own - after the last sentence, or between two - belong to the
    sentence before them (at the very start: the next one), instead of being dropped."""
    out, carry = [], ([], [])
    for x, k, u in map(parse_tags, split_sentences(text)):
        if x:
            out.append((x, carry[0] + k, carry[1] + u))
            carry = ([], [])
        elif out:
            out[-1] = (out[-1][0], out[-1][1] + k, out[-1][2] + u)
        else:
            carry = (carry[0] + k, carry[1] + u)
    return [(x, [t for t in tags.ALL if t in k], list(dict.fromkeys(u))) for x, k, u in out]


def text_to_speech(p: dict, out: Path, owner=None) -> dict:
    from ..tts import ENGINES, finish, trim, tts_cfg
    from . import clones
    sents = sentences(p["text"])
    data = {"segments": [{"tags": k} for _, k, _ in sents], "speakers": {"S1": {"voice": p["voice"]}}}
    prompt = out / "voice_prompt.wav"  # a clone's decrypted recording, for this job only
    try:
        if owner is not None:
            clones.write_reference(owner, p["voice"], prompt)
        tts = tts_cfg(data, {"tgt": {"tts": LANGS[p["lang"]]["tts"]}}, prompt)  # expressive voice for [laugh] ...
        texts = [tags.text_for_tts(x, k, tts["engine"], tts.get("lang", "")) for x, k, _ in sents]
        parts, info, sr = [], [], 24000
        for i, ((x, k, unknown), (audio, sr)) in enumerate(zip(sents, ENGINES[tts["engine"]](texts, tts))):
            f = out / f"s{i}.wav"
            finish(f, trim(audio), sr, k)
            a, sr = sf.read(f, dtype="float32")
            f.unlink()
            parts += [a, np.zeros(int(.35 * sr), dtype="float32")]
            info.append({"text": x, "tags": k, "unknown": unknown, "not_performed": tags.not_performed(k, tts["engine"])})
    finally:
        prompt.unlink(missing_ok=True)
    sf.write(out / "speech.wav", np.concatenate(parts[:-1]), sr)
    clone = tts["voice"].startswith("clone:")
    ffmpeg("-i", str(out / "speech.wav"), "-b:a", "160k", "-metadata", "comment=AI-generated speech (DUBBE" +
           (", consented voice clone, watermarked)" if clone else ")"), str(out / "speech.mp3"))
    if clone:
        clones.record_use(tts["voice"], owner["id"], sum(len(x) for x, _, _ in sents), "tts")
    return {"engine": tts["engine"], "voice": tts["voice"], "seconds": round(sf.info(out / "speech.wav").duration, 1),
            "sentences": info, "files": ["speech.mp3", "speech.wav"]}


def speech_to_text(p: dict, out: Path, video: Path) -> dict:
    from .. import asr, extract, segment, speakers, translate
    to = p.get("to") or ""
    cfg = config.load(p["src"], to or ("en" if p["src"] == "ko" else "ko"))
    cfg["keep_background"] = False
    for stage in (extract, asr, segment) + ((speakers,) if p.get("speakers") else ()) + ((translate,) if to else ()):
        stage.run(video, out, cfg)
    data = read_json(out / "segments.json")
    segs, names = data["segments"], {k: v.get("name") for k, v in (data.get("speakers") or {}).items()}
    files = {"transcript.srt": subtitles(segs, "src_text"), "transcript.vtt": subtitles(segs, "src_text", vtt=True),
             "transcript.txt": transcript(segs, "src_text", data.get("speakers"))}
    if to:
        files |= {"translation.srt": subtitles(segs, "tgt_text"), "translation.txt": transcript(segs, "tgt_text", data.get("speakers"))}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf8")
    return {"sentences": [{"start": s["start"], "end": s["end"], "src": s["src_text"], "tgt": s.get("tgt_text"), "flag": flags(s, cfg),
                           "speaker": names.get(s.get("speaker")) if len(names) > 1 else None} for s in segs],
            "speakers": len(names), "files": list(files)}


def find_speakers(p: dict, out: Path, video: Path) -> dict:
    """Who speaks when: speech recognition, then speaker detection on the separated voice (music does not join or split
    people), and a clip of each speaker to listen to. The full-quality voice stays for cloning a speaker (with consent)."""
    from .. import asr, extract, segment, separate, speakers
    cfg = config.load(p["src"], "en" if p["src"] == "ko" else "ko")
    cfg.update(keep_background=True, keep_voice_hq=True)
    for stage in (extract, separate, asr, segment, speakers):
        stage.run(video, out, cfg)
    data = read_json(out / "segments.json")
    data["speakers"], data["duration"] = data.get("speakers") or {}, sf.info(out / "audio.wav").duration
    x, sr = sf.read(out / "vocals44.wav", dtype="float32")
    for sp in data["speakers"]:  # their longest sentence, at most 12 s
        s = max((s for s in data["segments"] if s["speaker"] == sp), key=lambda s: s["end"] - s["start"])
        sf.write(out / f"{sp}.wav", x[int(s["start"] * sr):int(min(s["end"], s["start"] + 12) * sr)], sr)
        ffmpeg("-i", str(out / f"{sp}.wav"), "-b:a", "128k", str(out / f"{sp}.mp3"))
        (out / f"{sp}.wav").unlink()
    write_json(out / "segments.json", data)
    for f in ("audio.wav", "original.wav", "background.wav", "vocals.wav"):
        (out / f).unlink(missing_ok=True)
    return speaker_files(out)


def speaker_files(out: Path) -> dict:
    """Transcript and subtitles with the speakers' names, and the task's result. Runs again after a rename."""
    data = read_json(out / "segments.json")
    segs, spk = data["segments"], data["speakers"]
    named = segs if len(spk) < 2 else [{**s, "src_text": f"{spk[s['speaker']]['name']}: {s['src_text']}"} for s in segs]
    files = {"transcript.txt": transcript(segs, "src_text", spk), "transcript.srt": subtitles(named, "src_text"),
             "transcript.vtt": subtitles(named, "src_text", vtt=True)}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf8")
    talk = {sp: sum(s["end"] - s["start"] for s in segs if s["speaker"] == sp) for sp in spk}
    return {"duration": data["duration"],
            "speakers": [{"id": sp, "name": v["name"], "seconds": round(talk[sp], 1), "sentences": sum(s["speaker"] == sp for s in segs),
                          "share": round(100 * talk[sp] / (sum(talk.values()) or 1))} for sp, v in spk.items()],
            "sentences": [{"start": s["start"], "end": s["end"], "speaker": s["speaker"], "text": s["src_text"]} for s in segs],
            "files": list(files) + [f"{sp}.mp3" for sp in spk]}


def captions(p: dict, out: Path, tid: int) -> dict:
    """Subtitles as a service: speech recognition, speakers told apart (on the separated voice), an optional translation,
    and captions coloured by speaker. A dub's captions come from its project instead (p["project"]: its sentences, timed
    to the dubbed video). Burning them into the video is a second step, after the speakers are named (p["burn"])."""
    from .. import asr, extract, segment, separate, speakers, translate
    if not (out / "segments.json").exists():
        if p.get("project"):
            shutil.copy(project_work(p["project"]) / "segments.json", out / "segments.json")
        else:
            to = p.get("to") or ""
            cfg = config.load(p["src"], to or ("en" if p["src"] == "ko" else "ko"))
            cfg["keep_background"] = True
            for stage in (extract, separate, asr, segment, speakers) + ((translate,) if to else ()):
                stage.run(media(tid), out, cfg)
            for f in ("audio.wav", "original.wav", "background.wav", "vocals.wav"):
                (out / f).unlink(missing_ok=True)
        data = read_json(out / "segments.json")
        data["speakers"] = data.get("speakers") or {"S1": {"name": "Speaker 1"}}
        write_json(out / "segments.json", data)
    if p.get("burn"):
        caption_files(out, p, tid)  # the .ass with the current speaker names
        video = (project_work(p["project"]) / "dubbed.mp4" if p.get("project") else media(tid)).resolve()  # ffmpeg runs in out
        # libx264 on the CPU (this ffmpeg's NVENC needs NVIDIA driver 610+, the laptop has 592); the audio re-encoded so
        # any upload fits in an MP4
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"ass={p['burn']}.ass",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                        "-metadata", "comment=Captions made with AI speech recognition (DUBBE)", f"captioned.{p['burn']}.mp4"],
                       cwd=out, check=True)
    return caption_files(out, p, tid)


def project_work(pid: int) -> Path:
    from . import worker
    return worker.work(db.one("select * from projects where id=?", pid))


def has_picture(path: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True)
    return bool(r.stdout.strip()) and r.stdout.split()[0] not in ("mjpeg", "png")  # an MP3's cover art is no video


def caption_files(out: Path, p: dict, tid: int) -> dict:
    """Captions for each language - plain SRT for any platform, SRT and WebVTT coloured by speaker, ASS - and the task's
    result. Runs again after a speaker is renamed."""
    data = read_json(out / "segments.json")
    segs, spk = data["segments"], data["speakers"]
    langs = [(p["src"], "src_text")] + ([(p["to"], "tgt_text")] if p.get("to") else [])
    files = {}
    for lang, field in langs:
        files |= {f"{lang}.srt": subtitles(segs, field), f"{lang}.color.srt": subtitles(segs, field, speakers=spk),
                  f"{lang}.vtt": subtitles(segs, field, vtt=True, speakers=spk), f"{lang}.ass": ass(segs, field, spk, lang)}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf8")
    colors = speaker_colors(segs) or {sp: CAPTION_COLORS[0] for sp in spk}
    talk = {sp: sum(s["end"] - s["start"] for s in segs if s.get("speaker", "S1") == sp) for sp in spk}
    upload = None if p.get("project") else media(tid)
    video = upload.name if upload and has_picture(upload) else None
    burned = sorted(f.name for f in out.glob("captioned.*.mp4"))
    return {"langs": [lang for lang, _ in langs], "video": video, "burned": burned,
            "speakers": [{"id": sp, "name": v.get("name") or sp, "color": colors.get(sp, CAPTION_COLORS[0]),
                          "seconds": round(talk.get(sp, 0), 1)} for sp, v in spk.items()],
            "sentences": [{"start": s["start"], "speaker": s.get("speaker", "S1"), "src": s["src_text"], "tgt": s.get("tgt_text")}
                          for s in segs],
            "files": list(files) + burned + ([video] if video else [])}


def translate_text(p: dict, out: Path) -> dict:
    from .. import translate
    cfg = config.load(p["src"], p["tgt"])
    segs = [{"id": i + 1, "start": 0, "end": 0, "src_text": s, "tgt_text": None, "edited": False}
            for i, s in enumerate(split_sentences(p["text"]))]
    write_json(out / "segments.json", {"src": p["src"], "tgt": p["tgt"], "segments": segs})
    translate.run(None, out, cfg)
    segs = read_json(out / "segments.json")["segments"]
    (out / "translation.txt").write_text("\n".join(s["tgt_text"] for s in segs), encoding="utf8")
    return {"sentences": [{"src": s["src_text"], "tgt": s["tgt_text"], "conf": s["mt_conf"], "flag": flags(s, cfg),
                           "alts": [a["text"] for a in s["alts"][1:3]]} for s in segs], "files": ["translation.txt"]}


def isolate_voice(p: dict, out: Path, video: Path) -> dict:
    from .. import extract, separate
    cfg = config.load("en", "ko")  # languages do not matter for separation
    cfg.update(keep_background=True, background_floor_db=1e9, keep_voice_hq=True)  # keep both stems, full quality
    extract.run(video, out, cfg)
    separate.run(video, out, cfg)
    (out / "vocals44.wav").replace(out / "voice.wav")
    for stem in ("voice", "background"):
        ffmpeg("-i", str(out / f"{stem}.wav"), "-b:a", "192k", str(out / f"{stem}.mp3"))
    for f in ("audio.wav", "original.wav", "vocals.wav"):
        (out / f).unlink(missing_ok=True)
    return {"files": ["voice.mp3", "background.mp3", "voice.wav", "background.wav"]}


def main(tid: int) -> None:
    t = db.one("select * from tasks where id=?", tid)
    out = folder(tid)
    p = json.loads(t["params"])
    if t["kind"] == "tts":
        result = text_to_speech(p, out, db.one("select * from users where id=?", t["owner_id"]))
    elif t["kind"] == "translate":
        result = translate_text(p, out)
    elif t["kind"] == "stt":
        result = speech_to_text(p, out, media(tid))
    elif t["kind"] == "speakers":
        result = find_speakers(p, out, media(tid))
    elif t["kind"] == "captions":
        result = captions(p, out, tid)
        if p.get("burn"):  # done: the next run (a rename, another language) does not burn again unasked
            db.run("update tasks set params=? where id=?", json.dumps({**p, "burn": ""}, ensure_ascii=False), tid)
    else:
        result = isolate_voice(p, out, media(tid))
    db.run("update tasks set result=? where id=?", json.dumps(result, ensure_ascii=False), tid)


if __name__ == "__main__":
    main(int(sys.argv[1]))
