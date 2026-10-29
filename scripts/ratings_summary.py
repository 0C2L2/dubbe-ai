"""Summarize human ratings for one dubbed video (T-04 quality, T-07 flag precision/recall, rater agreement).

    python scripts/ratings_summary.py work/<clip>.<src>-<tgt> [--bad-below 60]

A sentence counts as bad when the rater marked any error or scored it below --bad-below.
Flag precision/recall uses only ratings made with flags hidden (evaluation mode).
"""
import argparse
import json
from pathlib import Path

from dubbe import read_json
from dubbe.ratings import load, summarize


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("work", type=Path)
    p.add_argument("--bad-below", type=int, default=60)
    a = p.parse_args()
    segs = read_json(a.work / "segments.json")["segments"]
    print(json.dumps(summarize(load(a.work), segs, a.bad_below), indent=1))


if __name__ == "__main__":
    main()
