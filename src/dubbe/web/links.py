"""A link in place of an upload: a YouTube video (your course, say) or any page or file yt-dlp can read.

The website looks the link up when the form is sent (title, length: the plan's limits are checked before anything is
downloaded) and writes it to <folder>/source.url; the worker downloads it before the job starts (fetch), as the file an
upload would have left there. app.public_url has already refused links to this machine or the local network."""
from pathlib import Path

SOURCE = "source.url"
MAX_BYTES = 2 * 1024 ** 3  # as an upload (app.MAX_UPLOAD)
VIDEO = ("bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]"
         "/bv*[height<=1080]+ba/b")  # H.264 first: YouTube gave AV1 otherwise, which not every player plays
AUDIO = "ba[ext=m4a]/ba/b"  # Speech to Text, Voice Isolator: the sound is all they use


def _ydl(**opts):
    from yt_dlp import YoutubeDL
    return YoutubeDL({"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, **opts})


def look(url: str) -> dict:
    """Title, length in minutes and whether it is a live stream; ValueError with a sentence for the user."""
    try:
        with _ydl() as y:
            info = y.extract_info(url, download=False, process=False)
    except Exception as e:  # yt-dlp says why: private video, not found, unsupported site ...
        raise ValueError(str(e).removeprefix("ERROR: ").split("\n")[0][:200]) from None
    if info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("This is a playlist: paste the link of one video.")
    live = bool(info.get("is_live")) or info.get("live_status") in ("is_live", "is_upcoming")
    if not live and not info.get("duration"):
        raise ValueError("The length of this video could not be read.")
    original, tracks = None, set()
    for f in info.get("formats") or []:  # YouTube: one audio track per language, the creator's or its own auto-dub
        lang = (f.get("language") or "").split("-")[0].lower()
        if not lang or f.get("vcodec") != "none":
            continue
        if (f.get("language_preference") or 0) >= 10 or "original" in (f.get("format_note") or ""):
            original = lang
        else:
            tracks.add(lang)
    return {"title": (info.get("title") or "Video")[:80], "minutes": (info.get("duration") or 0) / 60, "live": live,
            "original": original, "tracks": sorted(tracks - {original})}


def save(folder: Path, url: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SOURCE).write_text(url.strip(), encoding="utf8")


def waiting(folder: Path) -> bool:
    """A link was given and nothing is downloaded yet."""
    return (folder / SOURCE).exists()


def fetch(folder: Path, stem: str, video: bool = True, lang: str = "") -> Path:
    """Download the link in folder/source.url to folder/<stem>.<ext>: video up to 1080p with its original sound (yt-dlp
    puts the original track first), the sound only, or with the site's own audio track in `lang` (look: tracks)."""
    url = (folder / SOURCE).read_text(encoding="utf8").strip()
    form = VIDEO if video else AUDIO
    if lang.isalpha():
        form = f"bv*[height<=1080][vcodec^=avc1]+ba[language^={lang}][ext=m4a]/bv*[height<=1080]+ba[language^={lang}]"
    with _ydl(format=form, outtmpl=str(folder / f"{stem}.%(ext)s"), max_filesize=MAX_BYTES,
              overwrites=True, **({"merge_output_format": "mp4"} if video else {})) as y:
        y.download([url])
    got = next((f for f in folder.glob(f"{stem}.*") if f.is_file() and f.suffix not in (".part", ".ytdl")), None)
    if not got:
        raise RuntimeError("nothing was downloaded (the file may be over 2 GB)")
    (folder / SOURCE).unlink()
    return got
