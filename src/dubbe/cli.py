import argparse
import time
from pathlib import Path

from . import asr, config, extract, mux, read_json, report, segment, separate, shorten, timing, translate, tts, voice, write_json

STAGES = {"extract": extract, "separate": separate, "asr": asr, "segment": segment, "voice": voice, "translate": translate,
          "tts": tts, "shorten": shorten, "timing": timing, "mux": mux, "report": report}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="dubbe", description="Dub a video into another language.")
    p.add_argument("video", type=Path)
    p.add_argument("--src", default="ko")
    p.add_argument("--tgt", default="en")
    p.add_argument("--work", type=Path, default=Path("work"), help="folder for intermediate files")
    p.add_argument("--from", dest="start", choices=STAGES, help="re-run from this stage (e.g. after editing segments.json)")
    p.add_argument("--force", action="store_true", help="re-run every stage")
    p.add_argument("--slow-video", type=float, metavar="MAX", help="allow slowing the picture up to MAX (e.g. 1.2) "
                   "where the dub is longer, instead of only speeding up speech")
    p.add_argument("--no-background", action="store_true", help="voice only: drop music/effects (faster, no separation)")
    a = p.parse_args(argv)

    if not a.video.exists():
        raise SystemExit(f"Video not found: {a.video}")
    cfg = config.load(a.src, a.tgt)
    if a.slow_video:
        cfg["max_video_slow"] = a.slow_video
    if a.no_background:
        cfg["keep_background"] = False
    work = a.work / f"{a.video.stem}.{a.src}-{a.tgt}"
    work.mkdir(parents=True, exist_ok=True)
    log_path = work / "run.json"
    log = read_json(log_path) if log_path.exists() else {"done": {}}

    names = list(STAGES)
    first = names.index(a.start) if a.start else None
    for i, name in enumerate(names):
        if not a.force and name in log["done"] and (first is None or i < first):
            print(f"[skip] {name}")
            continue
        print(f"[run]  {name} ...", flush=True)
        t = time.perf_counter()
        try:
            STAGES[name].run(a.video, work, cfg)
        except Exception:
            print(f"[fail] {name} - earlier results kept in {work}; fix and re-run to resume")
            raise
        log["done"][name] = round(time.perf_counter() - t, 1)  # seconds, used for the cost comparison
        for later in names[i + 1:]:
            log["done"].pop(later, None)  # later stages are now stale
        write_json(log_path, log)
    print(f"Done: {(work / 'dubbed.mp4').resolve()}\nReview: {(work / 'report.html').resolve()}")


if __name__ == "__main__":
    main()
