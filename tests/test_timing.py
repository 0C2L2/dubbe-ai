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
