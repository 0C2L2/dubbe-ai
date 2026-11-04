import numpy as np

from dubbe.asr import drop_silent, plan_chunks, speaker_changes, whisper_model


def test_whisper_sizes_load_as_they_are_and_fine_tunes_from_the_cache(monkeypatch, tmp_path):
    assert whisper_model("large-v3-turbo") == "large-v3-turbo"
    monkeypatch.setenv("DUBBE_CACHE", str(tmp_path))
    done = tmp_path / "ct2" / "islomov--rubaistt_v2_medium"
    done.mkdir(parents=True)
    (done / "model.bin").write_bytes(b"x")  # converted before: used without converting again
    assert whisper_model("islomov/rubaistt_v2_medium") == str(done)

SR = 16000


def test_words_over_silence_are_dropped():
    audio = np.zeros(4 * SR, dtype="float32")
    audio[:SR] = 0.1 * np.sin(np.arange(SR) / 5)  # speech-like sound in the first second only
    words = [{"w": "real", "start": 0.2, "end": 0.8}, {"w": "invented", "start": 2.0, "end": 3.5}]
    assert [w["w"] for w in drop_silent(words, audio, SR, -60)] == ["real"]


def test_a_quiet_recording_keeps_its_words():
    audio = np.zeros(4 * SR, dtype="float32")
    audio[:3 * SR] = 0.0008 * np.sin(np.arange(3 * SR) / 5)  # about -65 dB: a quiet FLEURS reader, real speech
    words = [{"w": w, "start": i * 0.9, "end": i * 0.9 + 0.6} for i, w in enumerate(["quiet", "but", "real"])]
    words.append({"w": "invented", "start": 3.2, "end": 3.8})  # digital silence: still dropped
    assert [w["w"] for w in drop_silent(words, audio, SR, -60)] == ["quiet", "but", "real"]


def test_zero_length_word_does_not_crash():
    audio = np.full(SR, 0.1, dtype="float32")
    assert len(drop_silent([{"w": "x", "start": 0.5, "end": 0.5}], audio, SR, -60)) == 1


def test_chunks_cover_everything_and_cut_at_speaker_changes_and_pauses():
    speech = [(0, 20), (21, 50), (51, 70)]                 # pauses at 20.5 and 50.5
    chunks = plan_chunks(70, speech, [35.0, 35.4])          # 35.4: a change too close to the last cut is skipped
    assert chunks[0][0] == 0 and chunks[-1][1] == 70
    assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:]))   # no gap: nothing is left out
    assert all(b - a <= 28 for a, b in chunks)
    assert chunks[:3] == [(0, 20.5), (20.5, 35.0), (35.0, 50.5)]   # pause, speaker change, pause


def test_no_pause_means_a_hard_cut_at_the_window():
    assert plan_chunks(60, [(0, 60)], []) == [(0, 28.0), (28.0, 56.0), (56.0, 60)]


def test_speaker_changes_between_turns():
    turns = [{"start": 0, "end": 4, "speaker": "A"}, {"start": 5, "end": 8, "speaker": "A"},
             {"start": 9, "end": 12, "speaker": "B"}, {"start": 11.5, "end": 14, "speaker": "A"}]
    assert speaker_changes(turns) == [8.5, 11.5]   # gap -> its middle; overlap -> the new turn's start
    flicker = turns[:2] + [{"start": 8.6, "end": 8.8, "speaker": "B"}] + turns[2:3]
    assert speaker_changes(flicker) == [8.5]  # a 0.2 s turn is no place to cut: the sentence stays in one piece
