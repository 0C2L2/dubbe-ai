# DUBBE — Test Results

What has actually been run and measured. Newest first within each test. Plan and criteria: [test-plan.md](test-plan.md).

**Environment:** Windows 11, NVIDIA RTX 4060 Laptop (8 GB), Python 3.12, torch 2.8.0+cu128, versions pinned in `pyproject.toml`. Not yet run on Colab or a second machine.

## Unit tests

`pytest`: **26 passed** (sentence grouping, timing placement and video slow-down, silence filter, shorter-alternative choice, review flags, voice choice, video pieces). 2026-10-06.

## Test clips used

| Clip | What | Use |
|---|---|---|
| FLEURS ko_kr dev, 12 sentences, 2:43 | Read Korean speech with reference transcripts and translations (CC BY 4.0) | ASR accuracy, timing, background test (with added phone rings) |
| Private TV clip, Korean dub, 1:30 | Copyrighted; local only, never published | Real-world ko → en behaviour |
| Private animated lesson, English, 5:26 | CC BY-NC-ND; local only, never published | en → ko, timing under fast narration |

## Results

| Test | Result | Date | Notes |
|---|---|---|---|
| ASR accuracy (FLEURS ko) | **CER 9.9 %**, 12/12 sentences, 11/11 pauses found | 10-05 | WhisperX alignment found only 3/11 pauses → replaced by faster-whisper word timestamps; VAD filter skipped a sentence → off |
| ASR on separated voice vs. mix | 19.8 % vs **9.5 %** (repeatable) | 10-06 | ASR keeps reading the original mix |
| T-03 drift — FLEURS ko → en | **PASS**, max delay 0.00 s | 10-05 | |
| T-03 drift — TV clip ko → en | **PASS**, max delay 0.00 s | 10-06 | |
| T-03 drift — lesson en → ko | **PASS** with `--slow-video 1.2` (0.00 s); 0.37 s without | 10-06 | First run: FAIL, 2.43 s. Wider beam search + shorten → 0.63 s; slow-down → 0.00 s |
| T-08 long translations | max speech speed-up 1.30× → **1.18×**, overflowing sentences 16 → 8 → 0 | 10-06 | `shorten` replaced 1 sentence; most gain from wider beams and picture slow-down (+14 s, +4.5 % video length) |
| T-12 background kept | ring **−0.0 dB** vs original; **0** words of voice leak | 10-06 | PASS. Voice-only sources (TV clip) detected and mixed without residue |
| Voice/music balance | music 11.5 dB under the voice in the dub = original | 10-06 | was 17.5 dB before loudness matching |
| T-14 voice register | **95 %** Korean (calibration), **95 %** English (held out) | 10-06 | Pitch-only matching picked the wrong voice on the agitated multi-speaker TV scene → reviewer override |
| Korean TTS intelligibility (MMS) | Whisper round-trip near word-perfect | 10-06 | Voice sounds flat (plan C9) |
| Review flags (informal, FLEURS 15 sentences) | 3 flagged, 2 truly wrong; ~8 wrong by the author's reading | 10-05 | NLLB confidence misses confident errors ("Ghana" for Canaan, "line tenor"); T-07 needs the gold set |

## Run time (RTX 4060)

| Clip | Total | Slowest stages |
|---|---|---|
| FLEURS ko, 2:43 | ~55 s | translate 24 s, separate 10 s, ASR 8 s |
| Lesson en → ko, 5:26 | ~2.5 min | TTS (MMS) ~100 s, translate ~40 s |

## Not done yet

T-01 (fresh clone on another machine), T-02/T-04 (human raters), T-05/T-06/T-07 (gold set), T-09 (Korean rater), T-10 (multiple speakers), T-11 (cost table), T-13 (expressive voice).
