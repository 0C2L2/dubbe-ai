"""T-03 drift check: does dubbed speech stay on the source timeline over the whole clip?

    python scripts/drift_check.py work/<clip>.<src>-<tgt>/segments.json [--max 0.5]

Exit code 1 if any segment starts more than --max seconds late, or if the last minute
is on average later than the first minute (progressive drift).
"""
import argparse
import json
import sys


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("segments")
    p.add_argument("--max", type=float, default=0.5, help="max allowed delay per segment, s (TBD threshold)")
    a = p.parse_args()

    segs = json.load(open(a.segments, encoding="utf8"))["segments"]
    # delay vs. where the sentence should start on the output timeline (later if the video was slowed before it)
    off = [(s["start"], s["placed_start"] - s.get("out_start", s["start"])) for s in segs]
    end = segs[-1]["start"]
    first = [o for t, o in off if t < 60] or [0.0]
    last = [o for t, o in off if t >= end - 60] or [0.0]
    worst = max(off, key=lambda x: x[1])
    mean = lambda xs: sum(xs) / len(xs)

    print(f"segments: {len(segs)}   clip span: {end:.0f} s")
    print(f"max delay: {worst[1]:.3f} s (at {worst[0]:.1f} s)   mean delay: {mean([o for _, o in off]):.3f} s")
    print(f"mean delay first minute: {mean(first):.3f} s   last minute: {mean(last):.3f} s")
    ok = worst[1] <= a.max and mean(last) <= mean(first) + 0.1
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
