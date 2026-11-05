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
from . import db, links

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
            finish(f, trim(audio), sr, k, tts["engine"])
            a, sr = sf.read(f, dtype="float32")
            f.unlink()
            parts += [a, np.zeros(int(.35 * sr), dtype="float32")]
            info.append({"text": x, "tags": k, "unknown": unknown, "not_performed": tags.not_performed(k, tts["engine"])})
    finally:
        prompt.unlink(missing_ok=True)
        prompt.with_suffix(".txt").unlink(missing_ok=True)
    sf.write(out / "speech.wav", np.concatenate(parts[:-1]), sr)
    clone = tts["voice"].startswith("clone:")
    ffmpeg("-i", str(out / "speech.wav"), "-b:a", "160k", "-metadata", "comment=AI-generated speech (DUBBE" +
           (", consented voice clone, watermarked)" if clone else ")"), str(out / "speech.mp3"))
    if clone:
        clones.record_use(tts["voice"], owner["id"], sum(len(x) for x, _, _ in sents), "tts")
    return {"engine": tts["engine"], "voice": tts["voice"], "seconds": round(sf.info(out / "speech.wav").duration, 1),
            "sentences": info, "files": ["speech.mp3", "speech.wav"]}


def speech_to_text(p: dict, out: Path, video: Path) -> dict:
    from .. import asr, diarize, extract, segment, speakers, translate
    to = p.get("to") or ""
    cfg = config.load(p["src"], to or ("en" if p["src"] == "ko" else "ko"))
    cfg["keep_background"] = False
    who = p.get("speakers")
    for stage in (extract,) + ((diarize,) if who else ()) + (asr, segment) + ((speakers,) if who else ()) + ((translate,) if to else ()):
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
    from .. import asr, diarize, extract, segment, separate, speakers
    cfg = config.load(p["src"], "en" if p["src"] == "ko" else "ko")
    cfg.update(keep_background=True, keep_voice_hq=True)
    for stage in (extract, separate, diarize, asr, segment, speakers):
        stage.run(video, out, cfg)
    data = read_json(out / "segments.json")
    data["speakers"], data["duration"] = data.get("speakers") or {}, sf.info(out / "audio.wav").duration
    speaker_clips(out, data)
    write_json(out / "segments.json", data)
    for f in ("audio.wav", "original.wav", "background.wav", "vocals.wav"):
        (out / f).unlink(missing_ok=True)
    return speaker_files(out)


def speaker_clips(out: Path, data: dict) -> None:
    """A clip of each speaker to listen to: their longest sentence, at most 12 s, from the full-quality voice."""
    x, sr = sf.read(out / "vocals44.wav", dtype="float32")
    for sp in data["speakers"]:
        s = max((s for s in data["segments"] if s["speaker"] == sp), key=lambda s: s["end"] - s["start"], default=None)
        if s is None:
            continue
        sf.write(out / f"{sp}.wav", x[int(s["start"] * sr):int(min(s["end"], s["start"] + 12) * sr)], sr)
        ffmpeg("-y", "-i", str(out / f"{sp}.wav"), "-b:a", "128k", str(out / f"{sp}.mp3"))
        (out / f"{sp}.wav").unlink()


def sentence_words(segs: list[dict], words: list[dict]) -> list[list[int]]:
    """Which words (indices into words.json) each sentence holds: a word belongs to the last sentence starting at or
    before it, if it ends inside that sentence."""
    out, k = [[] for _ in segs], 0
    for i, w in enumerate(words):
        while k + 1 < len(segs) and segs[k + 1]["start"] <= w["start"] + 1e-3:
            k += 1
        if segs and segs[k]["start"] - 1e-3 <= w["start"] and w["end"] <= segs[k]["end"] + 1e-3:
            out[k].append(i)
    return out


def edit_speakers(out: Path, parts: list[dict]) -> dict:
    """A person's fix of who said what (Speaker Detection review): `parts` is the whole transcript again, in order -
    [{"speaker": "S1" or "new", "words": [word indices]}] - after moving words between sentences, splitting or
    joining sentences, or giving a sentence to another speaker. Every word must appear exactly once, in order, so
    nothing can be lost or duplicated. The sentences are rebuilt from the words, the result is marked as a person's
    (`speakers_edited`: a re-run never overwrites it) and the files and clips are written again."""
    data, words = read_json(out / "segments.json"), read_json(out / "words.json")["words"]
    old_words = sentence_words(data["segments"], words)
    before = [i for idx in old_words for i in idx]
    if not parts or [i for p in parts for i in p.get("words", [])] != before or any(not p.get("words") for p in parts):
        raise ValueError("every word must stay, exactly once and in order")
    # a sentence whose words did not change keeps its translation and a person's text fix (Subtitles); a changed one is
    # rebuilt from its words and translated again
    same = {tuple(ix): s for s, ix in zip(data["segments"], old_words)}
    spk = data["speakers"]
    new_id = f"S{max((int(k[1:]) for k in spk if k[1:].isdigit()), default=0) + 1}"
    src = data.get("src") or "en"
    join = config.load(src, "ko" if src == "en" else "en")["src"].get("join", " ")
    segs = []
    for n, p in enumerate(parts, 1):
        sp = new_id if p.get("speaker") == "new" else p.get("speaker")
        if sp not in spk and sp != new_id:
            raise ValueError(f"unknown speaker {sp}")
        ws = [words[i] for i in p["words"]]
        sc = [w["score"] for w in ws if "score" in w]
        seg = {"id": n, "start": ws[0]["start"], "end": ws[-1]["end"], "speaker": sp, "src_text": join.join(w["w"] for w in ws),
               "asr_conf": round(sum(sc) / len(sc), 3) if sc else None}
        old = same.get(tuple(p["words"]), {})
        seg |= {k: old[k] for k in ("tgt_text", "edited", "alts", "mt_conf", "text_edited") if k in old}
        if old.get("text_edited"):
            seg["src_text"] = old["src_text"]
        segs.append(seg)
    if any(s["speaker"] == new_id for s in segs):
        taken = {v.get("color") for v in spk.values()}
        spk[new_id] = {"name": f"Speaker {new_id[1:]}",  # a colour of its own when the others have theirs (Subtitles)
                       **({"color": next((c for c in CAPTION_COLORS if c not in taken), CAPTION_COLORS[0])} if taken - {None} else {})}
    used = {s["speaker"] for s in segs}
    data["speakers"] = {k: {**v, "maybe_same": [x for x in v.get("maybe_same", []) if x in used and x != k]}
                        for k, v in spk.items() if k in used}
    data.update(segments=segs, speakers_edited=True)
    if (out / "vocals44.wav").exists():
        speaker_clips(out, data)
    write_json(out / "segments.json", data)


def edit_caption_text(out: Path, lines: dict[int, tuple[str, str | None]], to: str) -> bool:
    """A person's fix of the caption text: {sentence id: (source text, translation)}. A fixed source line whose
    translation was left as it was is translated again; a fixed translation is the person's and stays. Returns True
    when something must be translated again."""
    data = read_json(out / "segments.json")
    for s in data["segments"]:
        if s["id"] not in lines:
            continue
        src, tgt = lines[s["id"]]
        tgt_changed = to and tgt is not None and tgt.strip() and tgt.strip() != (s.get("tgt_text") or "")
        if src.strip() and src.strip() != s["src_text"]:
            s.update(src_text=src.strip(), text_edited=True)
            if to and not tgt_changed:
                s.update(tgt_text=None, edited=False)  # the translation said the old line
        if tgt_changed:
            s.update(tgt_text=tgt.strip(), edited=True)
    write_json(out / "segments.json", data)
    return bool(to) and any(not s.get("tgt_text") for s in data["segments"])


def speaker_files(out: Path) -> dict:
    """Transcript and subtitles with the speakers' names, and the task's result. Runs again after a rename or an edit.
    Each sentence carries its words (index, text) so the review can move words between sentences."""
    data = read_json(out / "segments.json")
    segs, spk = data["segments"], data["speakers"]
    named = segs if len(spk) < 2 else [{**s, "src_text": f"{spk[s['speaker']]['name']}: {s['src_text']}"} for s in segs]
    files = {"transcript.txt": transcript(segs, "src_text", spk), "transcript.srt": subtitles(named, "src_text"),
             "transcript.vtt": subtitles(named, "src_text", vtt=True)}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf8")
    words = read_json(out / "words.json")["words"] if (out / "words.json").exists() else []
    idx = sentence_words(segs, words) if words else [[] for _ in segs]
    talk = {sp: sum(s["end"] - s["start"] for s in segs if s["speaker"] == sp) for sp in spk}
    return {"duration": data["duration"], "edited": bool(data.get("speakers_edited")),
            "speakers": [{"id": sp, "name": v["name"], "seconds": round(talk[sp], 1), "sentences": sum(s["speaker"] == sp for s in segs),
                          "share": round(100 * talk[sp] / (sum(talk.values()) or 1)), "maybe_same": v.get("maybe_same", [])}
                         for sp, v in spk.items()],
            "sentences": [{"start": s["start"], "end": s["end"], "speaker": s["speaker"], "text": s["src_text"],
                           "flag": bool(s.get("speaker_flag")), "words": [[i, words[i]["w"], words[i]["start"]] for i in ix]}
                          for s, ix in zip(segs, idx)],
            "files": list(files) + [f"{sp}.mp3" for sp in spk]}


def captions(p: dict, out: Path, tid: int) -> dict:
    """Subtitles as a service: speech recognition, speakers told apart (on the separated voice), an optional translation,
    and captions coloured by speaker. A dub's captions come from its project instead (p["project"]: its sentences, timed
    to the dubbed video). Burning them into the video is a second step, after the speakers are named (p["burn"])."""
    from .. import asr, diarize, extract, segment, separate, speakers, translate
    to = p.get("to") or ""
    if p.get("project"):
        from_project(out, p["project"])  # every run: the dub's sentences as they are now
    elif not (out / "segments.json").exists():
        cfg = config.load(p["src"], to or ("en" if p["src"] == "ko" else "ko"))
        cfg.update(keep_background=True, keep_voice_hq=True)  # the full-quality voice: a clip of each speaker, cloning
        for stage in (extract, separate, diarize, asr, segment, speakers) + ((translate,) if to else ()):
            stage.run(media(tid), out, cfg)
        data = read_json(out / "segments.json")
        data["duration"] = sf.info(out / "audio.wav").duration
        spk = data["speakers"] = data.get("speakers") or {"S1": {"name": "Speaker 1"}}
        if len(spk) > 1:  # each speaker's colour is kept from now on: a merge or a new person does not shift the others
            for i, sp in enumerate(sorted(spk, key=lambda k: (len(k), k))):
                spk[sp].setdefault("color", CAPTION_COLORS[i % len(CAPTION_COLORS)])
        speaker_clips(out, data)
        write_json(out / "segments.json", data)
        for f in ("audio.wav", "original.wav", "background.wav", "vocals.wav"):
            (out / f).unlink(missing_ok=True)
    data = read_json(out / "segments.json")
    if to and any(not s.get("tgt_text") for s in data["segments"]):  # sentences a person's fix rebuilt or reworded
        cfg = config.load(p["src"], to)
        cfg["only_missing"] = True
        translate.run(None, out, cfg)
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


def from_project(out: Path, pid: int) -> None:
    """A dub's captions: its sentences and speakers as they are now, so a fix in the dub's editor reaches them. A name or
    colour chosen on the Subtitles page (`custom`) stays."""
    data = read_json(project_work(pid) / "segments.json")
    old = (read_json(out / "segments.json").get("speakers") or {}) if (out / "segments.json").exists() else {}
    data["speakers"] = data.get("speakers") or {"S1": {"name": "Speaker 1"}}
    for sp, v in data["speakers"].items():
        if (old.get(sp) or {}).get("custom"):
            v.update({k: old[sp][k] for k in ("name", "color", "custom") if k in old[sp]})
    write_json(out / "segments.json", data)


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
    colors = speaker_colors(segs, spk) or {sp: CAPTION_COLORS[0] for sp in spk}
    talk = {sp: sum(s["end"] - s["start"] for s in segs if s.get("speaker", "S1") == sp) for sp in spk}
    upload = None if p.get("project") else media(tid)
    video = upload.name if upload and has_picture(upload) else None
    burned = sorted(f.name for f in out.glob("captioned.*.mp4"))
    # the words of each sentence, for the same "Fix speakers" review as Speaker Detection (an upload's own transcript only)
    words = read_json(out / "words.json")["words"] if not p.get("project") and (out / "words.json").exists() else []
    idx = sentence_words(segs, words) if words else [[] for _ in segs]
    clips = [f"{sp}.mp3" for sp in spk if (out / f"{sp}.mp3").exists()]
    return {"langs": [lang for lang, _ in langs], "video": video, "burned": burned, "edited": bool(data.get("speakers_edited")),
            "duration": data.get("duration") or max((s["end"] for s in segs), default=0) or 1,
            "speakers": [{"id": sp, "name": v.get("name") or sp, "color": colors.get(sp, CAPTION_COLORS[0]),
                          "seconds": round(talk.get(sp, 0), 1), "sentences": sum(s.get("speaker", "S1") == sp for s in segs),
                          "share": round(100 * talk.get(sp, 0) / (sum(talk.values()) or 1)), "maybe_same": v.get("maybe_same", [])}
                         for sp, v in spk.items()],
            "sentences": [{"id": s["id"], "start": s["start"], "end": s["end"], "speaker": s.get("speaker", "S1"),
                           "src": s["src_text"], "text": s["src_text"], "tgt": s.get("tgt_text"), "flag": bool(s.get("speaker_flag")),
                           "text_edited": bool(s.get("text_edited")),
                           "words": [[i, words[i]["w"], words[i]["start"]] for i in ix]} for s, ix in zip(segs, idx)],
            "files": list(files) + burned + ([video] if video else []) + clips}


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
    if t["kind"] in ("stt", "speakers", "captions", "isolate") and links.waiting(out):  # a pasted link: download it first
        try:
            links.fetch(out, "input", video=t["kind"] in ("speakers", "captions"))  # these two show the video
        except Exception as e:
            raise SystemExit(f"The file could not be downloaded from the link: {str(e).removeprefix('ERROR: ')[:300]}")
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
    elif t["kind"] == "live":  # Live Dubbing (beta): runs until the stream ends, MAX_MINUTES pass or Stop is pressed
        from .. import live
        result = live.run(out, p["url"], p["src"], p.get("voice") or "", tgt=p.get("tgt") or "en")
        db.run("update tasks set minutes=? where id=?", round(result["seconds"] / 60, 2), tid)  # counts what was dubbed
    else:
        result = isolate_voice(p, out, media(tid))
    db.run("update tasks set result=? where id=?", json.dumps(result, ensure_ascii=False), tid)


if __name__ == "__main__":
    main(int(sys.argv[1]))
