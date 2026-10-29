"""Voice clones (plan C13) and the voice library where owners share them (C14). Approved by the instructor (Q-010).

Rules:
- Only your own voice, recorded live in the browser while reading three sentences the server picked (no uploads, so
  nobody can clone a voice from someone else's video). Whisper checks that the recording says them.
- The recording is stored encrypted (Fernet, key in DUBBE_VOICE_KEY) and goes with the voice or the account. A dub or a
  text-to-speech job gets a decrypted copy for its own length only.
- Everything a clone says carries Chatterbox's watermark and the AI label, like every DUBBE voice.
- Sharing is opt-in and listed only after an admin listened to it; the owner can stop it at any time. Uses by other
  people are counted and the owner sees what they would earn - nothing is paid during the non-commercial beta.

    python -m dubbe.web.clones <voice id>    (run by the worker: checks a recording and makes the voice's sample)
"""
import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from . import db

RATE = 0.03  # US$ per 1,000 characters, what ElevenLabs pays voice owners (docs/project-plan.md C14); shown, not paid
MAX_CER = 0.3  # how far the recording may be from the shown sentences (Whisper's own error on read speech: ~10 %)
MIN_SECONDS = 8  # Chatterbox needs more than 5 s of voice
FRESH_S = 1800  # the sentences are valid for 30 minutes after they were shown
SENTENCES = {
    "en": ["The morning train was late, so we walked along the river instead.",
           "Please put the green folder on the second shelf by the window.",
           "My grandmother grew tomatoes, beans and sunflowers in her garden.",
           "We should check the weather before we drive to the mountains.",
           "A quiet library is the best place to finish a long report.",
           "The children laughed when the small dog chased its own tail.",
           "Could you send me the slides from yesterday's meeting?",
           "Fresh bread from the bakery smells wonderful in the morning.",
           "The museum opens at ten and closes early on Sundays.",
           "I usually drink a cup of tea while I read the news.",
           "Turn left at the bridge and you will see the blue house.",
           "The concert was so loud that we could barely hear each other."],
    "ko": ["아침 기차가 늦어서 우리는 강을 따라 걸어갔어요.",
           "초록색 서류철을 창가 쪽 두 번째 선반에 놓아 주세요.",
           "할머니는 정원에서 토마토와 콩, 해바라기를 키우셨어요.",
           "산으로 출발하기 전에 날씨를 먼저 확인해야 해요.",
           "조용한 도서관은 긴 보고서를 끝내기에 가장 좋은 곳이에요.",
           "작은 강아지가 자기 꼬리를 쫓자 아이들이 웃었어요.",
           "어제 회의 발표 자료를 보내 주실 수 있나요?",
           "아침에 빵집에서 갓 구운 빵 냄새가 정말 좋아요.",
           "박물관은 열 시에 문을 열고 일요일에는 일찍 닫아요.",
           "저는 보통 뉴스를 읽으면서 차를 한 잔 마셔요.",
           "다리에서 왼쪽으로 돌면 파란 집이 보일 거예요.",
           "콘서트가 너무 시끄러워서 서로 말소리가 거의 안 들렸어요."]}
SAMPLE = {"en": "Hello, this is my voice in DUBBE. Everything it says is labelled as AI.",
          "ko": "안녕하세요, DUBBE에서 만든 제 목소리입니다. 이 목소리로 만든 음성에는 AI 표시가 붙습니다."}
LANGS = yaml.safe_load((Path(__file__).parent.parent / "languages.yaml").read_text(encoding="utf8"))


def enabled() -> bool:
    """Cloning needs the encryption key and the Chatterbox environment."""
    from ..tts import CHATTERBOX_PY
    return bool(os.environ.get("DUBBE_VOICE_KEY")) and CHATTERBOX_PY.exists()


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(os.environ["DUBBE_VOICE_KEY"].encode())


def folder(vid: int) -> Path:
    return db.ROOT / "voices" / str(vid)


def script(lang: str) -> str:
    return " ".join(secrets.SystemRandom().sample(SENTENCES[lang], 3))


def save(vid: int, name: str, data: bytes) -> None:
    folder(vid).mkdir(parents=True, exist_ok=True)
    (folder(vid) / f"{name}.enc").write_bytes(_fernet().encrypt(data))


def load(vid: int, name: str) -> bytes:
    return _fernet().decrypt((folder(vid) / f"{name}.enc").read_bytes())


def voice_id(key: str | None) -> int | None:
    m = re.fullmatch(r"clone:(\d+)", key or "")
    return int(m[1]) if m else None


def usable(u) -> list:
    """Clones in this user's voice pickers: their own checked ones, and listed ones they added from the marketplace."""
    return db.all_("select voices.*, users.name owner_name from voices join users on users.id=owner_id where status='ready' "
                   "and (owner_id=? or (shared='listed' and exists(select 1 from voice_saves where voice_id=voices.id "
                   "and user_id=?))) order by owner_id<>?, voices.id desc", u["id"], u["id"], u["id"])


# ---------------------------------------------------------------- marketplace: listings, search, reviews

CATEGORIES = ["Narration", "Education", "Conversation", "Characters", "Advertising", "News & documentary"]
TAGS = ["calm", "warm", "clear", "deep", "bright", "energetic", "friendly", "formal", "young", "mature"]
SORTS = {"popular": "uses + saves desc, rating desc", "new": "shared_at desc", "rating": "rating desc, reviews desc"}


def _listed(uid: int, where: str, args: list, order: str = "voices.id desc") -> list:
    return db.all_("select voices.*, users.name owner_name, "
                   "(select count(*) from voice_uses where voice_id=voices.id and user_id<>voices.owner_id) uses, "  # by others, like earnings
                   "(select coalesce(sum(chars), 0) from voice_uses where voice_id=voices.id and user_id<>voices.owner_id) chars, "
                   "(select count(*) from voice_saves where voice_id=voices.id) saves, "
                   "(select avg(stars) from voice_reviews where voice_id=voices.id) rating, "
                   "(select count(*) from voice_reviews where voice_id=voices.id) reviews, "
                   "exists(select 1 from voice_saves where voice_id=voices.id and user_id=?) saved "
                   f"from voices join users on users.id=owner_id where {where} order by {order}", uid, *args)


def market(u, q: str = "", lang: str = "", cat: str = "", sort: str = "popular") -> list:
    """Listed voices for the store front, filtered by language, category and a search in name, description, tags, owner."""
    where, args = "status='ready' and shared='listed'", []
    for col, val in (("lang", lang), ("category", cat)):
        if val:
            where += f" and {col}=?"
            args.append(val)
    if q.strip():
        where += " and (voices.name like ? or description like ? or tags like ? or users.name like ?)"
        args += [f"%{q.strip()}%"] * 4
    return _listed(u["id"], where, args, SORTS.get(sort, SORTS["popular"]) + ", voices.id desc")


def listing(u, vid: int):
    rows = _listed(u["id"], "voices.id=?", [vid])
    return rows[0] if rows else None


# ---------------------------------------------------------------- Voice Studio: the publisher's side

STEPS = ["Recorded", "Checked", "Listing", "In review", "Live"]


def step(v) -> tuple[int, str]:
    """Where a voice is on its way to the marketplace: an index into STEPS and its state (active, failed, done)."""
    if v["status"] in ("waiting", "checking"):
        return 1, "active"
    if v["status"] == "failed":
        return 1, "failed"
    return {"listed": (4, "done"), "pending": (3, "active"), "rejected": (3, "failed")}.get(v["shared"], (2, "active"))


def studio(u) -> dict:
    """The publisher's numbers over all their voices: uses and adds by other people, rating, what it would earn."""
    mine = "from {t} join voices on voices.id=voice_id where owner_id=?"
    r = db.one(f"select (select count(*) {mine.format(t='voice_uses')} and user_id<>owner_id) uses, "
               f"(select coalesce(sum(chars), 0) {mine.format(t='voice_uses')} and user_id<>owner_id) chars, "
               f"(select count(*) {mine.format(t='voice_saves')}) saves, (select avg(stars) {mine.format(t='voice_reviews')}) rating, "
               f"(select count(*) {mine.format(t='voice_reviews')}) reviews", *[u["id"]] * 5)
    return {**dict(r), "earn": round(r["chars"] / 1000 * RATE, 4)}


def listing_error(description: str, category: str, tags: list[str], complete: bool = True) -> str | None:
    """complete: everything filled in (to submit, or while listed); a draft may leave fields empty."""
    d = description.strip()
    return ("Describe the voice in 10 to 300 characters." if (complete or d) and not 10 <= len(d) <= 300 else
            "Choose a category." if (complete or category) and category not in CATEGORIES else
            "Choose up to three tags from the list." if len(tags) > 3 or not set(tags) <= set(TAGS) else None)


def own_voices(u) -> list:
    """The publisher's voices with their marketplace numbers, for the Studio."""
    return _listed(u["id"], "owner_id=? and status<>'draft'", [u["id"]])


def can_use(u, key: str | None):
    vid = voice_id(key)
    return vid and db.one("select * from voices where id=? and status='ready' and (owner_id=? or shared='listed')",
                          vid, u["id"])


def write_reference(u, key: str | None, dest: Path) -> bool:
    """Decrypt the reference recording to dest if this user may use the voice (checked again at every use: the owner
    may have stopped sharing or deleted it). The caller deletes dest when the job ends."""
    if not (enabled() and can_use(u, key)):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)  # a first dub: the pipeline has not made its work folder yet
    dest.write_bytes(load(voice_id(key), "reference"))
    return True


# ---------------------------------------------------------------- a speaker of a video, cloned with consent

def speaker_file(pid: int, sp: str) -> Path:
    """Only inside the project: never in anyone's voices, never shared, deleted with the project folder."""
    return db.ROOT / "projects" / str(pid) / "speakers" / f"{sp}.enc"


def speaker_clip(work: Path, segs: list[dict], sp: str) -> tuple[bytes | None, float, str]:
    """One speaker's longest sentences from the separated voice (up to 20 s) as WAV, the seconds of speech, and what
    those sentences say. No WAV below MIN_SECONDS."""
    import io

    import numpy as np
    import soundfile as sf
    wav = next(f for f in (work / "vocals44.wav", work / "vocals.wav", work / "audio.wav") if f.exists())
    x, sr = sf.read(wav, dtype="float32")
    x = x.mean(1) if x.ndim > 1 else x
    parts, total, said = [], 0.0, []
    for s in sorted((s for s in segs if s.get("speaker", "S1") == sp), key=lambda s: s["start"] - s["end"]):  # longest first
        parts += [x[int(s["start"] * sr):int(s["end"] * sr)], np.zeros(int(.2 * sr), "float32")]
        total += s["end"] - s["start"]
        said.append(s["src_text"])
        if total >= 20:
            break
    if total < MIN_SECONDS:
        return None, total, ""
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(parts), sr, format="WAV")
    return buf.getvalue(), total, " ".join(said)


def make_speaker_clone(pid: int, work: Path, segs: list[dict], sp: str) -> float:
    """The reference recording of one speaker of this video, after the uploader confirmed consent, encrypted next to
    the project. Returns the seconds of speech; nothing is stored below MIN_SECONDS."""
    wav, total, _ = speaker_clip(work, segs, sp)
    if wav:
        speaker_file(pid, sp).parent.mkdir(parents=True, exist_ok=True)
        speaker_file(pid, sp).write_bytes(_fernet().encrypt(wav))
    return total


def write_speaker_reference(pid: int, key: str, dest: Path) -> bool:
    """Decrypt a project's speaker clone ("video:S2") to dest for one job; the caller deletes dest afterwards."""
    f = speaker_file(pid, key.split(":", 1)[1])
    if not (enabled() and f.exists()):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_fernet().decrypt(f.read_bytes()))
    return True


def record_use(key: str, uid: int, chars: int, kind: str) -> None:
    db.run("insert into voice_uses(voice_id, user_id, chars, kind, created_at) values(?,?,?,?,?)",
           voice_id(key), uid, chars, kind, db.now())


def stats(v) -> dict:
    """Uses by other people and what the owner would earn at RATE (nothing is paid in the beta)."""
    r = db.one("select count(*) n, coalesce(sum(chars), 0) chars from voice_uses where voice_id=? and user_id<>?",
               v["id"], v["owner_id"])
    return {"uses": r["n"], "chars": r["chars"], "earn": round(r["chars"] / 1000 * RATE, 4)}


def delete(vid: int) -> None:
    shutil.rmtree(folder(vid), ignore_errors=True)
    db.run("delete from voices where id=?", vid)


def cer(ref: str, hyp: str) -> float:
    """Character error rate, ignoring spaces, punctuation and case."""
    a, b = (re.sub(r"[\W_]+", "", t.lower()) for t in (ref, hyp))
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[-1] / max(len(a), 1)


def check(vid: int) -> None:
    """The consent check: long enough, and saying the sentences that were shown. Then the recording becomes the
    voice's reference and a short sample is made with the clone."""
    import soundfile as sf

    from .. import device, ffmpeg, free_gpu
    from ..tts import ENGINES, trim
    v = db.one("select * from voices where id=?", vid)
    with tempfile.TemporaryDirectory() as tmp:
        raw, wav = Path(tmp) / "recording", Path(tmp) / "reference.wav"
        raw.write_bytes(load(vid, "recording"))
        (folder(vid) / "recording.enc").unlink()  # from here on only the checked reference is kept, or nothing
        ffmpeg("-i", str(raw), "-ac", "1", "-ar", "24000", str(wav))
        audio, sr = sf.read(wav, dtype="float32")
        audio = trim(audio)
        if len(audio) / sr < MIN_SECONDS:
            return fail(vid, f"The recording has {len(audio) / sr:.1f} s of voice; please read all three sentences "
                             f"(at least {MIN_SECONDS} s).")
        sf.write(wav, audio, sr)
        import torch  # noqa: F401 - loads the CUDA DLLs (cublas) that ctranslate2 needs on Windows
        from faster_whisper import WhisperModel
        dev = device()
        model = WhisperModel("large-v3-turbo", device=dev, compute_type="float16" if dev == "cuda" else "int8")
        heard = "".join(s.text for s in model.transcribe(str(wav), language=v["lang"], beam_size=5)[0]).strip()
        del model
        free_gpu()
        if cer(v["script"], heard) > MAX_CER:
            return fail(vid, f'The recording does not say the sentences that were shown (heard: "{heard[:200]}").', heard)
        save(vid, "reference", wav.read_bytes())
        engine = LANGS[v["lang"]]["tts"]["clone"]
        audio, sr = next(ENGINES[engine]([SAMPLE[v["lang"]]], {"engine": engine, "voice": f"clone:{vid}", "lang": v["lang"],
                                                               "prompt": str(wav)}))
        sf.write(Path(tmp) / "sample.wav", trim(audio), sr)
        ffmpeg("-i", str(Path(tmp) / "sample.wav"), "-b:a", "160k", "-metadata",
               "comment=AI-generated: DUBBE voice clone, made with the owner's consent (watermarked)", str(folder(vid) / "sample.mp3"))
    db.run("update voices set status='ready', heard=?, error=null, checked_at=? where id=?", heard, db.now(), vid)


def fail(vid: int, error: str, heard: str | None = None) -> None:
    shutil.rmtree(folder(vid), ignore_errors=True)  # a failed check keeps no recording
    db.run("update voices set status='failed', error=?, heard=?, checked_at=? where id=?", error, heard, db.now(), vid)


if __name__ == "__main__":
    check(int(sys.argv[1]))
