from dubbe.mux import pieces


def test_pieces_cover_the_clip_and_merge_unslowed_ranges():
    segs = [{"start": 1.0, "slow": 1.0}, {"start": 3.0, "slow": 1.2}, {"start": 5.0, "slow": 1.0}, {"start": 7.0, "slow": 1.0}]
    assert pieces(segs, 10.0) == [(0.0, 3.0, 1.0), (3.0, 5.0, 1.2), (5.0, 10.0, 1.0)]
