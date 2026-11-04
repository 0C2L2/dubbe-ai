from dubbe.timing import out_duration, place


def segs(*spec):
    """spec: (source start, tts duration) tuples"""
    return [{"start": s, "tts_dur": d} for s, d in spec]


def test_fits_unchanged():
    s = place(segs((0, 2.0), (5, 2.0)), total=10, max_stretch=1.3)
    assert [x["stretch"] for x in s] == [1.0, 1.0]
    assert [x["placed_start"] for x in s] == [0, 5]


def test_slightly_long_is_sped_up():
    s = place(segs((0, 6.0), (5, 2.0)), total=10, max_stretch=1.3)
    assert s[0]["stretch"] == 1.2 and s[0]["overflow"] == 0


def test_too_long_capped_and_flagged():
    s = place(segs((0, 8.0), (5, 2.0)), total=10, max_stretch=1.3)
    assert s[0]["stretch"] == 1.3 and s[0]["overflow"] > 0.05
    assert s[1]["placed_start"] > 5  # next one waits instead of overlapping


def test_delay_does_not_accumulate():
    # one overflowing segment, then a pause: later segments are back on their source start
    s = place(segs((0, 8.0), (5, 1.0), (10, 1.0), (15, 1.0)), total=20, max_stretch=1.3)
    assert s[1]["placed_start"] > 5
    assert s[2]["placed_start"] == 10 and s[3]["placed_start"] == 15



def test_a_little_long_dub_ends_late_instead_of_speeding_up():
    s = place(segs((0, 5.5), (5, 2.0)), total=10, max_stretch=1.3, late=1.0)
    assert s[0]["stretch"] == 1.0 and s[0]["overflow"] == 0  # 0.5 s past the next start: allowed, not sped up
    assert s[1]["placed_start"] == 5.5  # ... and the next one waits for it
    s = place(segs((0, 6.6), (5, 2.0)), total=10, max_stretch=1.3, late=1.0)
    assert s[0]["stretch"] == 1.1  # more than 1 s over: sped up only for the rest
    assert place(segs((0, 2.0), (5, 5.5)), total=10, max_stretch=1.3, late=1.0)[1]["stretch"] == 1.1  # the last: no late
    s = place(segs((0, 5.8), (5, 5.8), (10, 1.0), (20, 1.0)), total=30, max_stretch=1.3, late=1.0)
    assert s[1]["placed_start"] == 5.8 and s[1]["stretch"] > 1.0  # starts 0.8 late: only 0.2 s left to borrow
    assert s[2]["placed_start"] - s[2]["out_start"] <= 1.0  # back-to-back lines never fall more than 1 s behind


def test_short_dub_is_slowed_towards_the_speaker():
    a = [{"start": 0, "end": 4.0, "tts_dur": 3.6}, {"start": 5, "end": 9.0, "tts_dur": 2.0}, {"start": 10, "end": 11, "tts_dur": 1.5}]
    s = place(a, total=12, max_stretch=1.3, min_stretch=0.85)
    assert s[0]["stretch"] == 0.9    # 3.6 s of dub for 4 s of talking: played at 0.9x, ends with the speaker
    assert s[1]["stretch"] == 0.85   # far shorter: slowed only as far as min_stretch
    assert s[2]["stretch"] == 1.0    # longer than the talking but fits the slot: unchanged
    assert place(a, total=12, max_stretch=1.3)[0]["stretch"] == 1.0  # default: never slowed


def test_video_slowing_shares_the_extra_time():
    # needs 1.44x: picture slows 1.2x, speech speeds up 1.2x instead of 1.44x
    s = place(segs((0, 7.2), (5, 1.0)), total=10, max_stretch=1.3, max_slow=1.2)
    assert s[0]["slow"] == 1.2 and s[0]["stretch"] == 1.2 and s[0]["overflow"] == 0
    assert s[1]["out_start"] == 6.0  # the next sentence moves with the slowed picture
    assert s[1]["placed_start"] == 6.0  # ...and is not late on the new timeline
    assert out_duration(s, 10) == 11.0


def test_no_slowing_when_it_fits_or_disabled():
    assert place(segs((0, 2.0), (5, 1.0)), total=10, max_stretch=1.3, max_slow=1.2)[0]["slow"] == 1.0
    assert place(segs((0, 7.2), (5, 1.0)), total=10, max_stretch=1.3)[0]["slow"] == 1.0


def test_delivery_helpers():
    import numpy as np
    from dubbe.timing import fade, limit
    a = np.ones(1000, dtype="float32")
    f = fade(a, 1000)  # 10 ms = 10 samples at each end
    assert f[0] == 0 and f[-1] == 0 and f[500] == 1 and f.dtype == np.float32
    x = np.array([0.5, 0.95, 1.5, -3.0], dtype="float32")
    y = limit(x)
    assert y[0] == 0.5 and np.all(np.abs(y) <= 1) and y[2] > y[1] > 0.9 and y[3] < -0.9  # loud stays loud, never past full scale
