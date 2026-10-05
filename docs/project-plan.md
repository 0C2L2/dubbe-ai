# DUBBE — Technical Build Plan (draft v2, 2026-10-05)

How to build DUBBE step by step, from an empty repo to the final demo. Each step says **what to build, how, and how to check it**. Order follows the course rule: **Baseline complete → Target → Stretch**. Week numbers assume Week 1 = Sep 1 (today = Week 6) — adjust to the real calendar.

Related: [architecture.md](architecture.md) (C4, stages, `languages.yaml`) · [test-plan.md](test-plan.md) (T-01…T-11) · [data-sources.md](data-sources.md).

---

## 0. Tech stack

| Purpose | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | Colab default is fine |
| Audio / video | ffmpeg ≥ 6 (system binary) | Called with `subprocess.run` |
| ASR + word timestamps | `faster-whisper` (`large-v3-turbo`, built-in word timestamps) | GPU float16; CPU int8 fallback |
| Translation | `transformers` + `facebook/nllb-200-distilled-600M` | `sentencepiece` needed |
| TTS | `kokoro` (English); `melotts` (Korean, Target) | Kokoro needs `espeak-ng` (apt) |
| Audio arrays | `numpy`, `soundfile` | Mixing the dub track |
| Config | `pyyaml` | `languages.yaml` |
| Quality (Target) | `unbabel-comet` (CometKiwi QE, COMET), `jiwer` (CER/WER) | CometKiwi is gated → HF token in `.env` |
| Tests | `pytest` | Only for pure logic |

Pin exact versions in `pyproject.toml` once Step 2 works.

## 1. Repository layout

```
dubbe-ai/
├── pyproject.toml            # deps + `dubbe` console script
├── .env.example              # HF_TOKEN=
├── src/dubbe/
│   ├── cli.py                # argparse, stage runner, --from / --force
│   ├── languages.yaml        # per-language models and rules
│   ├── config.py             # load + validate languages.yaml
│   ├── extract.py  asr.py  segment.py  translate.py
│   ├── tts.py                # one synthesize() per engine (kokoro, melotts)
│   ├── timing.py  mux.py
│   └── report.py             # Target
├── tests/
│   ├── test_segment.py
│   └── test_timing.py
├── scripts/
│   ├── drift_check.py        # T-03
│   └── eval_propagation.py   # T-05 (Target)
├── notebooks/colab_spike.ipynb
└── work/<clip_id>/           # git-ignored, one folder per run
```

## 2. Data contracts (the files between stages)

All times in seconds (float, 3 decimals). All text UTF-8.

`words.json` (ASR output)
```json
{"language": "ko", "duration": 183.420,
 "words": [{"w": "오늘은", "start": 0.512, "end": 0.981, "score": 0.93}]}
```

`segments.json` (single source of truth, grows stage by stage)
```json
{"src": "ko", "tgt": "en",
 "segments": [{
   "id": 1, "start": 0.512, "end": 4.210,
   "src_text": "오늘은 신경망에 대해 이야기하겠습니다.",
   "tgt_text": "Today we will talk about neural networks.",
   "edited": false,
   "asr_conf": 0.91, "qe": null,
   "tts_dur": null, "stretch": null, "placed_start": null, "overflow": null,
   "flag": null}]}
```

`timing.json` is not separate: timing writes `tts_dur`, `stretch`, `placed_start`, `overflow` into `segments.json`. Fewer files, one place to read.

---

## Phase A — Environment check — **done 2026-10-05** (local RTX 4060; Colab not tried)

The project tab requires proving the free path early. Do it by hand in a notebook before writing the package.

**A1. Colab setup**
```bash
!apt-get -qq install -y ffmpeg espeak-ng
!pip -q install faster-whisper transformers sentencepiece kokoro soundfile pyyaml
```
Check: `torch.cuda.is_available()` is `True` (Runtime → T4 GPU).

**A2. Run every stage by hand on one 2-minute Korean clip** (cells in `notebooks/colab_spike.ipynb`):
1. `ffmpeg -y -i clip.mp4 -vn -ac 1 -ar 16000 audio.wav`
2. faster-whisper transcribe with word timestamps (Step B2 code)
3. Group words into sentences — naive version: split on `.?!` only
4. NLLB translate each sentence (Step B4 code)
5. Kokoro synthesize each sentence (Step B5 code)
6. Place each WAV at its sentence start in a silent array, write `dub.wav`
7. `ffmpeg` mux (Step B7 command)

**A3. Record:** total run time, peak GPU memory (`torch.cuda.max_memory_allocated()`), which stage is slowest. Repeat on a CPU-only laptop with `compute_type="int8"`.

**Gate A:** a 2-min dubbed MP4 plays in Colab. If not → smaller Whisper (`medium`) or CPU-only TTS; if still not, raise with the instructor immediately (Q-004).

---

## Phase B — Baseline pipeline — **built** (B1–B9); human rating (T-02/T-04) still open

Build one stage per pull request, in this order. A stage = one function `run(work_dir, cfg)` that reads its input file and writes its output file.

### B0. Scaffold
- Generate from `humblebeeai/module-python-template`; add `[project.scripts] dubbe = "dubbe.cli:main"`.
- `languages.yaml` with `ko` and `en` (see architecture.md).
- `config.py`: `load(src, tgt) -> dict`; fail with a clear message if a language or field is missing.

Check: `pip install -e .` then `dubbe --help` works from a fresh clone.

### B1. extract
```bash
ffmpeg -y -i input.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le work/<id>/audio.wav
```
Also store video duration (`ffprobe -v error -show_entries format=duration -of csv=p=0 input.mp4`).

Check: WAV is 16 kHz mono; duration equals video ± 0.1 s.

### B2. asr → `words.json` — **built** (`src/dubbe/asr.py`)
```python
import torch  # first: loads the CUDA DLLs ctranslate2 needs on Windows
from faster_whisper import WhisperModel
model = WhisperModel("large-v3-turbo", device=dev, compute_type="float16")  # "int8" on CPU
segs, info = model.transcribe(wav, language=cfg["src"]["whisper"], word_timestamps=True,
                              vad_filter=False, condition_on_previous_text=False)
words = [{"w": w.word, "start": w.start, "end": w.end, "score": w.probability} for s in segs for w in s.words]
```
Decisions from testing on FLEURS Korean (2026-10-05):
- WhisperX + wav2vec2 alignment was tried first: only 3/11 known sentence pauses found, 5% of speech placed inside silences, near-zero confidence on long stretches. faster-whisper's own word timestamps: 11/11 pauses, 0%.
- `vad_filter=True` and `condition_on_previous_text=True` each made it skip a whole sentence (11/12 covered, CER ~20%). Both off: 12/12, CER 9.9%.
- `score` = word probability (real ASR confidence, mean 0.94 on the test clip).
- Whisper's fallback decoding is not fully repeatable (CER varied 20–24% between identical runs with the old settings) — evaluate on more than one run.

Check: every word has `start < end`, times are non-decreasing, last word ends ≤ audio duration.

### B3. segment → `segments.json` *(known hard part #1)*
Rule-based, per-language rules from `languages.yaml`:
1. Walk words in order, accumulate the current sentence.
2. **Close** the sentence when either: the word matches `sentence_end` (e.g. `[.?!]` or Korean endings `다/요/까`) **and** the pause to the next word ≥ 0.3 s; **or** the pause ≥ 0.8 s.
3. **Force split** if the sentence exceeds 15 s or 40 words → split at its longest internal pause.
4. **Merge** a fragment shorter than 1.0 s into its neighbour across the smaller pause.
5. `start` = first word start, `end` = last word end, `src_text` = words joined (no spaces for languages with `join: ""` if ever needed).

Thresholds live in `languages.yaml` defaults so they can be tuned per language.

Tests (`tests/test_segment.py`, synthetic word lists, no models): punctuation split; pause-only split; 20-s run gets force-split; tiny fragment merged; every word lands in exactly one segment.

### B4. translate
```python
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
name = "facebook/nllb-200-distilled-600M"
tok = AutoTokenizer.from_pretrained(name, src_lang=cfg["src"]["nllb"])
model = AutoModelForSeq2SeqLM.from_pretrained(name).to(device)
batch = tok(texts, return_tensors="pt", padding=True).to(device)
out = model.generate(**batch, forced_bos_token_id=tok.convert_tokens_to_ids(cfg["tgt"]["nllb"]),
                     num_beams=4, max_new_tokens=200)
tgt = tok.batch_decode(out, skip_special_tokens=True)
```
- Batch 16 sentences; skip segments with `edited: true` (human text wins).
- Output is one string per input → structured-output problem (known hard part #2) does not arise with NLLB.

Check: every segment has non-empty `tgt_text`; no source-script characters left (e.g. no Hangul in English output).

### B5. tts → `tts/<id>.wav`
One adapter per engine in `tts.py`, same signature:
```python
def synthesize(text: str, voice: str) -> tuple[np.ndarray, int]: ...

# kokoro
from kokoro import KPipeline
pipe = KPipeline(lang_code="a")                      # 'a' = American English
audio = np.concatenate([a for _, _, a in pipe(text, voice=voice, speed=1.0)])
return audio, 24000
```
- Engine and voice come from `languages.yaml[tgt].tts`.
- Write each WAV, store `tts_dur` in `segments.json`.
- Trim leading/trailing silence (> −40 dB) so durations are honest.

Check: one non-silent WAV per segment.

### B6. timing → `dub.wav` *(known hard part #3, prevents drift)*
For each segment *i* in order:
1. `slot = next_start − start` (time until the next sentence begins; last segment → video end).
2. `ratio = tts_dur / slot`.
   - `ratio ≤ 1.0` → no change.
   - `1.0 < ratio ≤ 1.3` → speed up by `ratio` (`ffmpeg -filter:a atempo=<ratio>`).
   - `ratio > 1.3` → speed up by 1.3, mark `overflow = tts_dur/1.3 − slot`, `flag = "overflow"`.
3. `placed_start = max(start, previous_placed_end)` — each sentence aims for **its own source start**, so a late sentence can only delay the next one until the next pause absorbs it. Delay never accumulates across the clip.
4. Add the samples into a silent float32 array of video length at `placed_start × sr`; clip to [−1, 1]; write `dub.wav`.

Store `stretch`, `placed_start`, `overflow` per segment.

Tests (`tests/test_timing.py`, synthetic durations): fits → unchanged; 1.2× → stretched; 1.6× → capped + overflow flag; one long sentence delays only the next one; offsets return to 0 after a gap.

### B7. mux → `dubbed.mp4`
```bash
ffmpeg -y -i input.mp4 -i dub.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k -shortest dubbed.mp4
```
Video is copied (no re-encode → fast, no quality loss). Original audio is dropped (voice-only track; background music is out of Baseline scope).

Check: one video + one audio stream; duration = source ± 0.5 s.

### B8. CLI and resume
```
dubbe input.mp4 --src ko --tgt en [--out out/] [--from tts] [--force]
```
- Stages run in fixed order: `extract, asr, segment, translate, tts, timing, mux`.
- A stage is skipped if its output exists, unless `--force` or it is at/after `--from`.
- On failure: stop, keep earlier files, print the failed stage.
- Log wall-clock time per stage to `work/<id>/run.json` (needed for the cost comparison later).

**Human review loop (course rule: AI output must be editable):** reviewer edits `tgt_text` in `segments.json`, sets `"edited": true`, runs `dubbe input.mp4 --from tts`.

### B9. Baseline tests
- `scripts/drift_check.py`: for every segment `offset = placed_start − start`; print max, mean, and mean offset in first vs. last minute; save a plot. → **T-03**
- Fresh clone → README steps → run on all test clips. → **T-01**
- Rating round (watchability + rubric) by English speakers. → **T-02, T-04**

**Gate B (Baseline done):** T-01…T-04 pass. Nothing from Phase C starts before this.

---

## Phase C — Target (Weeks 11–13), in priority order

### C1. Quality signals + review flags — **built** (`report.py`), CometKiwi still to add
Status 2026-10-06: `asr_conf` (Whisper word probability), `mt_conf` (NLLB's own sequence probability, no extra model) and `overflow` drive the flags. Finding: confident errors are not caught — "line tenor" (misheard name) had ASR 0.91; NLLB confidence missed most wrong translations on FLEURS and is lower overall for en→ko (33/42 flagged at 0.5), so **thresholds must be per language pair**. CometKiwi below is the next signal to test.
- `asr_conf`: mean word score of the segment (from B2).
- `qe`: CometKiwi (`Unbabel/wmt22-cometkiwi-da`, reference-free) on (`src_text`, `tgt_text`). Gated model → `HF_TOKEN` from `.env`. Fallback if unavailable: BLASER 2.0-QE, or skip with a warning.
- `stretch` / `overflow` from B6.
- `flag` = reason list, e.g. `["low_asr", "low_qe", "overflow"]`. Thresholds start as guesses, then are tuned on the gold set (C3) to catch most rater-marked errors.

### C2. `report.html` — **built**
Plain HTML from Python (no framework): summary (segments, % flagged, per-stage counts) + one row per flagged segment: time, source text, translation, scores, reason, `<audio>` link to `tts/<id>.wav`. Opens offline in a browser.

### C3. Error-propagation study — `scripts/eval_propagation.py` (T-05, T-06, T-07)
On the gold set (human source transcript + human translation):
1. **ASR error:** CER of ASR text vs. gold transcript (`jiwer.cer`, after removing spaces and punctuation for Korean).
2. **MT run twice:** (a) on ASR text, (b) on gold transcript. COMET with reference (`Unbabel/wmt22-comet-da`) vs. gold translation. `score(b) − score(a)` = what ASR errors cost translation; `1 − score(b)` side = MT's own error.
3. **TTS/timing:** synthesize gold translation, re-transcribe with English Whisper, WER vs. the text; plus % segments stretched/overflowing.
4. **Attribution:** for every rater-marked bad segment, record the first stage whose output is wrong → share of errors per stage.
5. **Flag quality:** precision/recall of C1 flags against rater-marked segments.

Output a CSV + one chart per question. This is the centre of the demo (step 4: trace one failed segment stage by stage).

### C4. Timing fallback for long translations (T-08) — **built** (`shorten.py` stage)
`translate` keeps NLLB's 4 best beams (`num_beams=8`) as `alts`; for segments whose speech exceeds `slot × 1.3`, `shorten` picks the shortest alternative with ≥ 85 % of the best confidence, re-synthesizes, keeps it only if really shorter.
Result on a 5:26 English → Korean video: max delay 2.43 s → 0.63 s, mean 0.49 s → 0.06 s, overflowing segments 16 → 8. Most of the gain came from the wider beam search (its best translations are more concise); `shorten` replaced 1 segment. Still above the 0.5 s threshold at one fast-narration stretch. Next upgrade if needed: Qwen3-8B (4-bit, local) with "translate in ≤ N words".

### C5. Cost per minute (T-11)
From `run.json`: seconds of compute per minute of video, on Colab T4 and on CPU. Convert at a stated GPU-hour price (Colab free = $0, rented T4 for reference). Compare with ElevenLabs ($0.33–2.20/min) and human dubbing; state the quality gap using the rating scores.

### C6. Second language pair (T-09) — only if approved (Q-005) — **runs** (Korean TTS: MMS)
Built 2026-10-06 with Meta MMS-TTS Korean (`facebook/mms-tts-kor`, CC BY-NC 4.0, local, needs `uroman`) instead of MeloTTS (hard to install on Windows). Whisper round-trip of the synthetic Korean was near word-perfect. Still needed for T-09: a fluent Korean rater and a licensed English clip.
Original plan: English → Korean: add `melotts` adapter to `tts.py`, check `languages.yaml` entries, add an English test clip (e.g. MIT OCW, licence checked), repeat T-01/T-02/T-04 with a fluent Korean rater. No pipeline code changes beyond the adapter — this is the proof that the many → many design works.

### C7. Multiple speakers (T-10) — optional
pyannote speaker diarization (gated → `HF_TOKEN`) → `speaker` per word → per segment by majority. `languages.yaml` voice list → map speaker N to voice N.

### C8. Keep background sound (music, effects, a phone ringing) — **built** (`separate.py`, `mux.py`)
Result 2026-10-06 (`scripts/background_check.py`, T-12): FLEURS Korean + 8 phone rings between sentences → ring level in the dub −0.0 dB vs. original (pass: within −3 dB); Korean Whisper on `background.wav` found 0 words (no voice leak); separation 9.5 s for 2:43 on an RTX 4060.
**Changed from the plan:** step 3 rejected — ASR on the separated voice stem had CER 19.8 % vs 9.5 % on the original mix (repeatable), so ASR keeps reading the mix and the separation is used only for the background. Also, `translate` no longer uses `generate(output_scores=True)` (it stored a 256k-vocab table per beam per step and ran out of GPU memory); confidence is now one teacher-forced forward pass per candidate.
Original plan below.
**Problem.** `mux` replaces the whole soundtrack with the dubbed voice, so everything that is not speech disappears: a phone ringing, a door, music, traffic. In a drama scene that changes the meaning ("the phone rings" → silence); in a lecture it removes intro music and demo sounds. Not a DoD item, but it decides watchability (Stretch: human watchability evaluation) and is very visible in the demo.

**Idea.** Split the original audio into a *voice* stem and a *background* stem (music source separation), translate only the voice, then put the new voice on top of the untouched background.

```
original.wav ──► separate ──► vocals.wav ──► asr → segment → translate → tts → shorten → timing → dub.wav
                          └─► background.wav ─────────────────────────────────────────────────┐
                                                                         mix (duck background) ◄┘ → mux
```

**Steps**
1. `extract`: also keep a full-quality copy, `original.wav` (source sample rate, stereo) — separation needs it; ASR keeps using 16 kHz mono.
2. New stage `separate` (after `extract`): Demucs v4 `htdemucs`, two stems → `vocals.wav`, `background.wav`. MIT licence, local, ~2–3 GB GPU memory, roughly 10–30 s per minute of audio on GPU (to measure). Fallback if Demucs will not install on Python 3.12 / torch 2.8: `audio-separator` (MDX-Net/UVR models, MIT).
3. `asr` reads `vocals.wav` instead of the mix — cleaner input when music is loud (compare CER both ways; keep the better).
4. `timing` unchanged: builds `dub.wav` (new voice only).
5. `mux` → mix: `background + dub voice`, with **ducking** — background lowered ~6 dB only while a dubbed sentence plays (we know exactly when from `placed_start` / `tts_dur`), full volume otherwise, so the phone ring between lines is heard at its original level. ffmpeg `volume` with a time expression or `sidechaincompress`; then mux as today.
6. Option `--background off` keeps today's voice-only behaviour (fast path, CPU-only machines).

**Data contract additions:** `work/<clip>/original.wav`, `vocals.wav`, `background.wav`.

**Risks**
| Risk | What you would hear | Mitigation / check |
|---|---|---|
| Voice bleed — remnants of the original speech left in `background.wav` | Faint Korean murmur under the English voice | Ducking; **objective check:** run source-language Whisper on `background.wav` — should recognize almost no words |
| Non-speech vocal sounds (laughs, sighs, crowd) land in the vocals stem | They disappear with the original voice | Accept and list in known limits |
| Separation artifacts when music and speech overlap heavily | "Watery" music | Try `htdemucs_ft` (fine-tuned, slower); report it |
| Runtime on CPU | Slow | `--background off` |
| Licence | — | Separating audio does not change the video's licence rules; same clip rules apply |

**Tests (T-12, new)**
1. Synthetic, objective: FLEURS Korean speech mixed with a known sound at known times (e.g. ffmpeg-generated phone ring beeps between sentences). After dubbing: (a) ring energy in `dubbed.mp4` at those times within ~3 dB of the original; (b) source-language Whisper on `background.wav` finds ≤ 1 word per minute.
2. Real clip (private test only): the phone/car scene — listening check that ringing and ambience survive.
3. Watchability rating with vs. without background (feeds the Stretch human evaluation).

**Effort:** about 1–2 days — one new stage (~30 lines), small changes to `extract`, `asr`, `mux`, one test script. **When:** after C1–C5; earlier only if the instructor counts it toward watchability.

### C9. Expressive voice — intonation and emotion instead of a flat, robotic read — planned
**Problem.** The dub reads every sentence the same way. Kokoro (English) is fairly natural but has no emotion control; MMS (Korean) sounds flat and robotic. A worried phone call, a joke and a definition all come out in one tone, and questions sometimes lose their rising intonation. Not a DoD item, but it decides watchability (Stretch: human watchability evaluation; Stretch: "voice characteristics preserved across languages").

**Hard rule (project tab, Risk): no voice cloning — not the speaker, not team members.** We transfer the speaker's *expression* (emotion label, energy, speed, question/exclamation) as numbers and labels, never their *voice*. The source audio is **never** passed to a TTS model as a reference/prompt. Several expressive TTS models offer a "zero-shot" mode that clones from a reference clip — we use only their built-in preset voices. Confirm with the instructor that expression transfer is allowed (Q-009).

```
background.wav ─────────────────────────────────────────────────────────────────────────┐
original.wav ──► separate ──► vocals.wav ──► express: emotion + energy + rate + pitch range │
                                                   │  (per segment, from the source voice) │
segments ──► translate ──► tts(text, preset voice, emotion, speed, intensity) ──► timing ──► mix
```

**What we measure per segment (new stage `express`, after `segment`)**
| Signal | How | Used for |
|---|---|---|
| Emotion (neutral, happy, sad, angry, surprised, fearful…) + confidence | Speech emotion recognition on the separated **voice stem** for that segment's time range (candidate: emotion2vec+; fallback: a text emotion classifier on the source sentence) | TTS emotion/style control |
| Energy | RMS level of the voice stem vs. the clip's average | Loudness gain of the dubbed sentence; "intensity" control |
| Speaking rate | Characters (or syllables) per second of the source sentence vs. the clip's average | TTS speed (bounded 0.9–1.15×, also helps timing) |
| Pitch range | F0 standard deviation (e.g. `librosa.pyin`) vs. the clip's average | Expressiveness/exaggeration control |
| Sentence type | Source punctuation and endings (`?`, `!`, Korean `-까/-요?`) | Make sure the translation keeps `?`/`!` — TTS intonation keys on punctuation |

Note: the voice stem was rejected for ASR (artefacts doubled CER), but emotion and pitch estimates are far less sensitive to them — check this in step 5.

**Steps (in order, each one usable on its own)**
1. **Punctuation fidelity — cheapest win (~½ day).** If the source sentence is a question/exclamation and the translation lost its `?`/`!`, restore it before TTS. Rising intonation on questions comes back for free with both Kokoro and MMS.
2. **Speed and energy from the source (~½ day).** Per segment: TTS `speed` from the source speaking rate (Kokoro has `speed`; MMS has `speaking_rate`), gain from the source energy. Excited fast speech stays fast; a quiet aside stays quiet.
3. **A better Korean voice — bake-off (1–2 days).** MMS is the most robotic part. Candidates with built-in voices and local, free licences: MeloTTS Korean (MIT), CosyVoice instruct mode with a preset Korean speaker (Apache 2.0; can take an emotion instruction), Chatterbox Multilingual with its stock voice (MIT; has an "exaggeration" knob). Score each on: Whisper round-trip error (intelligibility, already used), automatic naturalness MOS (UTMOS), speed on the RTX 4060, install pain on Windows, and a short listening test. Licences and Korean support to be verified during the bake-off.
4. **Emotion transfer (2–3 days).** `express` stage + mapping from emotion label/intensity to whatever the chosen engine supports: CosyVoice instruction text ("speak sadly"), Chatterbox exaggeration value, Kokoro speed/gain only. Low-confidence emotions → neutral (a wrong emotion is worse than none).
5. **Evaluate (1 day)** — see tests below; keep each step only if it helps.

**Timing with expression — the main trade-off.** Expressive speech is slower and has more pauses, and the time is already tight: on the 5:26 English → Korean video, 23 of 42 sentences were longer than their slot even with the flat voice (median 1.01×). Rule: **timing beats expression.** Order of tools, most natural-sounding first:
1. **Budget before synthesis:** the slot (`next start − start`) is known before TTS, so pass it as a speed target (`speed` in Kokoro, `speaking_rate` in MMS). Speed set inside the TTS sounds far better than time-stretching the audio afterwards.
2. **Synthesize → measure → re-synthesize once** at `speed = duration / slot` for sentences that still do not fit.
3. **Compress internal pauses:** silences > 0.25 s inside the synthesized sentence → 0.15 s (expressive engines add long pauses at commas and "…").
4. **Fit wins:** final speed = max(expressive speed, speed needed to fit) — a sad, slow line gets a bit less slow, never late.
5. **Expression only where there is room:** if a sentence needs > 1.15× to fit, synthesize it neutral (no extra pauses or exaggeration).
6. **Duration-aware wording:** `shorten` gets a character budget = slot × the voice's measured characters per second; upgrade path is a local LLM asked for "≤ N syllables".
7. **Borrow silence:** allow a start up to ~0.2 s early when the previous dubbed line has already ended.
8. **Last resort (as today):** `atempo` ≤ 1.3×, then flag for review.
Report both sides of the trade-off: drift check + % segments stretched (timing) and T-13 scores (expression), per step.

**Data contract additions (per segment in `segments.json`):** `emotion`, `emotion_conf`, `energy_db`, `src_rate`, `f0_std`, `tts_params` (exactly what was sent to the TTS, for the report and reproducibility). The report gets an emotion column and a new flag `emotion_mismatch`.

**Tests (T-13, new)**
1. **Emotion agreement (objective):** run the same speech-emotion model on the source segment and on the dubbed segment → % of segments with the same emotion. Before vs. after step 4.
2. **Intonation:** questions — pitch rise at the end of the dubbed sentence (F0 of the last 300 ms vs. the sentence average) for segments whose source ends with `?`.
3. **Naturalness:** UTMOS score of dubbed speech, before vs. after; plus a blind A/B listening test (old vs. new voice) with the rating rubric — feeds the Stretch human evaluation.
4. **No regression:** Whisper round-trip error and the drift check must not get worse (expressive speech is often slower).

**Risks**
| Risk | Effect | Mitigation |
|---|---|---|
| Accidental cloning | Breaks the course rule | Never pass source audio to TTS; code review checks the TTS call has no reference-audio argument |
| Emotion recognizer wrong (acted vs. real speech, Korean vs. English training data) | Comic or wrong tone | Confidence threshold → neutral; human can override `emotion` in `segments.json` like `tgt_text` |
| Expressive models are bigger/slower | Longer runs, 8 GB GPU limit | Load one model at a time (already the pattern); measure in the bake-off |
| More expressive = longer speech | More timing overflow | Speed bounds; `shorten` stage already handles overflow |
| Windows install problems (CosyVoice, MeloTTS) | Lost days | Bake-off time-boxed; keep MMS as fallback |

**Effort:** about 5–7 days in total; steps 1–2 alone (~1 day) already remove much of the flat sound. **When:** after the Target items (C1–C5) — it is Stretch. If the instructor counts it toward watchability, steps 1–2 can go earlier.

### C10. Voice matching — a preset voice that sounds like the speaker's *type* of voice (no cloning) — **built, single speaker** (`voice.py`)
Result 2026-10-06: register split 122 Hz (torchaudio pitch detector, which reads low) → 95 % on FLEURS ko (calibration) and 95 % on held-out FLEURS en (`scripts/voice_check.py`). 26 Kokoro English presets measured (`scripts/tag_voices.py`) and stored in `languages.yaml`.
**Changed from the plan:** (1) two registers (lower/higher), not three — the data separates cleanly at one split; (2) a preset's register is its own f/m label, pitch only picks within the group — raw pitch crossed perceived voice type (male `bm_george` 126 Hz measures above female `af_bella`/`af_kore` 123 Hz).
**Found limit:** on the Breaking Bad test clip the median was 131 Hz → "higher" → a female preset, wrong. Per sentence the pitch ranged 114–151 Hz: an agitated phone call raises pitch, and the scene has more than one speaker. Pitch-only matching is reliable for calm single-speaker speech (lectures), not for emotional multi-speaker scenes; those need C7 diarization and a timbre-based feature. The reviewer override (`override: true` in `segments.json`, then `--from tts`) fixed it and survives re-runs; the report now shows the chosen voice and how to change it. Korean output has one voice (MMS), so matching has no effect there until the C9 bake-off adds Korean presets. Pitch nudge (step 4) not built.
Original plan below.
**Problem.** Every speaker is dubbed with the same preset voice: a deep male voice comes out as a light female one (or the reverse), and in a two-person scene both people sound identical. Viewers notice this immediately.

**Match, don't clone.** Measure a few audible properties of the original voice and pick the **closest preset voice** from the TTS engine's built-in library, then nudge it slightly. The speaker's timbre / voice "fingerprint" is never copied and no source audio is ever given to the TTS (same hard rule as C9). We describe voices by **pitch register (lower / higher voice)**, not by guessing the person's sex: it is what listeners actually hear, needs no extra model, is more reliable (pitch, not identity), and avoids labelling people. A reviewer can override the choice. Covered by Q-009.

```
vocals.wav ──► per speaker: median pitch, pitch range, speaking rate ──► voice profile
                                                                          │
languages.yaml voice library (each preset tagged: register, pitch, style) ─► pick closest preset
                                                                          │
tts(text, chosen preset) ──► optional small pitch shift toward the speaker (≤ ±2 semitones)
```

**Steps**
1. **Voice profile per speaker (~½ day).** On the separated voice stem (C8), over that speaker's sentences: median F0 and F0 range (`librosa.pyin`), speaking rate. Register = lower / middle / higher from median F0 (starting thresholds ~145 Hz and ~190 Hz, tuned in step 5). Single speaker first; with C7 diarization, one profile per speaker.
2. **Tag the voice library (~½ day).** In `languages.yaml`, each TTS voice gets measured attributes, e.g. `{id: am_michael, register: lower, f0: 110}`. Measure them by synthesizing one fixed sentence per preset and running the same pitch analysis — no guessing from names. Kokoro English has many American/British presets in both registers.
3. **Pick + keep consistent (~½ day).** Closest preset by register, then nearest median F0. The same speaker keeps the same voice for the whole video; different speakers get different presets (no two speakers share a voice when the library allows).
4. **Small pitch nudge (optional, ~½ day).** Shift the chosen preset toward the speaker's median F0, capped at ±2 semitones (larger shifts sound artificial). ffmpeg `rubberband` or `librosa.effects.pitch_shift`; keep only if the A/B listening test prefers it.
5. **Evaluate (~1 day).** See tests.

**Korean output limit.** MMS Korean has a single voice, so matching needs a Korean engine with several presets in different registers — add "number of Korean presets, both registers" to the C9 bake-off criteria (CosyVoice instruct presets, MeloTTS, Chatterbox; an online engine such as Edge TTS would only be considered if Q-003 allows external services).

**Data contract additions.** `segments.json` top level: `"speakers": {"S1": {"median_f0": 118, "f0_range": 34, "rate": 4.1, "register": "lower", "voice": "am_michael", "pitch_shift": -1.0, "override": false}}`; per segment: `speaker`. The report shows each speaker's chosen voice; a reviewer can change `voice` and re-run `--from tts`.

**Privacy.** Only a few numbers per speaker are stored (pitch, rate) — no voice embeddings or speaker "fingerprints" (biometric data), and nothing leaves `work/` (git-ignored).

**Tests (T-14, new)**
1. **Register accuracy:** FLEURS lists each recording's speaker gender, which serves as a free proxy label for voice register — measure how often step 1 picks the matching register over many FLEURS speakers (Korean and English). Also the team-recorded clips (consent covers this use).
2. **Pitch distance:** |median F0 of the dub − median F0 of the source| per speaker, before (fixed preset) vs. after matching.
3. **Two-speaker clip (T02):** the two speakers get different voices, each consistent through the clip.
4. **Listening A/B:** "Does the dubbed voice fit the person on screen?" fixed preset vs. matched — feeds the Stretch human evaluation.

**Risks**
| Risk | Mitigation |
|---|---|
| Pitch register ≠ how a person identifies; wrong-seeming voice | Describe as register only; reviewer override in `segments.json`; never shown as a label about the person |
| Too few presets (Korean) | Bake-off criterion; fall back to the single voice + pitch nudge |
| Music/noise disturbs pitch estimate | Use the separated voice stem, median over many sentences, ignore unvoiced frames |
| Pitch shift artefacts | Cap ±2 semitones; drop step 4 if the A/B test does not prefer it |
| Drifting into cloning | No audio prompts to TTS, no embeddings — only register, pitch and rate numbers |

**Effort:** about 2–3 days single-speaker, +1 day once C7 diarization exists. **When:** Stretch, after the Target items; pairs naturally with C7 (multiple speakers) and C9 (expressive voice).

---

## Phase D — Stretch (only if chosen Target items are done)

- Larger human watchability study.
- Qwen3 vs. NLLB comparison on the gold set.
- Fine-tuning / distillation — only with instructor approval.
- Out of scope: voice cloning, lip sync.

## Phase E — Mid-course review (≈ Week 9) and final delivery (Weeks 14–15)

**Mid-course review:** `docs/functional-requirements.md` (Baseline items as requirements), C3 diagram of `src/dubbe/`, current test results, risks.

**Final:**
1. Pin all versions; fresh clone on another machine → T-01 passes.
2. README: install, `.env` setup, how to get the data, how to run, expected outputs (screenshots of `segments.json` and `report.html`), fallbacks (CPU mode, no CometKiwi), test results, known limits.
3. Demo video 2–3 min following the project tab script: business case → original → dubbed → **one failed segment traced stage by stage** → cost per minute.
4. Contribution record from the commit history.

---

## Timeline summary

| Weeks | Phase | Exit check |
|---|---|---|
| 6–7 | A — Environment check | 2-min dubbed MP4 from a notebook, Colab + CPU numbers |
| 7–10 | B — Baseline pipeline | T-01…T-04 pass |
| ≈ 9 | Mid-course review | FRD, C3, test results |
| 11–13 | C — Target | Report, propagation study, timing fallback, cost; 2nd pair if approved |
| 14–15 | E — Final | Fresh-clone run, README, demo video |

## Technical risks

| Risk | Early sign | Response |
|---|---|---|
| Colab T4 runs out of memory | OOM in A2 | Free each model after its stage; `int8`; Whisper `medium` |
| Words without timestamps | `start` missing on numbers | Interpolate from neighbours (B2) |
| Bad sentence boundaries | Translations cut mid-thought | Tune B3 thresholds on a team clip with known sentences |
| Translations much longer than source | Many `ratio > 1.3` | C4 n-best shortest; report the rate honestly |
| Gated models (CometKiwi, pyannote) unavailable | 401 from Hugging Face | Accept terms + `HF_TOKEN`; fallback BLASER-QE / single speaker |
| espeak-ng missing for Kokoro | TTS import error | `apt-get install espeak-ng`, documented in README |
