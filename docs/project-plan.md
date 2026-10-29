# DUBBE — Technical Build Plan (draft v2, 2026-10-05)

How to build DUBBE step by step, from an empty repo to the final demo. Each step says **what to build, how, and how to check it**. Order follows the course rule: **Baseline complete → Target → Stretch**. Week numbers assume Week 1 = Sep 1 (today = Week 6) — adjust to the real calendar.

Related: [architecture.md](architecture.md) (C4, stages, `languages.yaml`) · [test-plan.md](test-plan.md) (T-01…T-11) · [data-sources.md](data-sources.md).

---

## 0. Tech stack

| Purpose | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | Colab default is fine |
| Audio / video | ffmpeg ≥ 6 (system binary) | Called with `subprocess.run` |
| ASR + word timestamps | `faster-whisper` (`large-v3` for Korean, `large-v3-turbo` for English since 2026-10-16, test-results C23; built-in word timestamps) | GPU float16; CPU int8 fallback |
| Translation | `ctranslate2` + NLLB-200 3.3B int8 (`KomorebiAI/nllb-200-3.3B-int8-ct2`, tokenizer `facebook/nllb-200-3.3B`); was `nllb-200-distilled-600M` until 2026-10-16 (test-results C23) | `sentencepiece` needed |
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

### C7. Multiple speakers (T-10) — **built** (`speakers.py`)
Built 2026-10-15 without pyannote (no gated model, no `HF_TOKEN`): one voice fingerprint per sentence (`microsoft/wavlm-base-plus-sv`), sentences grouped by voice (average linkage, cosine threshold 0.3 in `languages.yaml`), S1 = the person who speaks most. Each speaker gets their own voice (C10), and transcripts can be downloaded by speaker. The reviewer renames, merges ("same person as…") or splits ("+ New speaker") in the editor; corrections are kept on re-runs. With the uploader's consent, a speaker can be cloned from the video for that project only (C13). The website also has it as its own tool, **Speaker Detection** (who speaks when, transcript by speaker, a speaker cloned into the uploader's voices with consent: private, never listed). Result: test results C21 — right on clearly different voices, merges similar ones (two men in the Breaking Bad scene). The fingerprints stay in memory; only the speaker label per sentence is saved.
Original plan: pyannote speaker diarization (gated → `HF_TOKEN`) → `speaker` per word → per segment by majority. `languages.yaml` voice list → map speaker N to voice N.

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
3. **A better Korean voice — bake-off (1–2 days).** *Decided 2026-10-15: Chatterbox Multilingual, built-in voice (MIT) — Whisper round-trip CER 4.1 % vs MMS 15.3 %, 5.1 s per sentence (test-results C9a/C9b); MMS stays as the fallback. A native-speaker listening test is still open.* MMS is the most robotic part. Candidates with built-in voices and local, free licences: MeloTTS Korean (MIT), CosyVoice instruct mode with a preset Korean speaker (Apache 2.0; can take an emotion instruction), Chatterbox Multilingual with its stock voice (MIT; has an "exaggeration" knob). Score each on: Whisper round-trip error (intelligibility, already used), automatic naturalness MOS (UTMOS), speed on the RTX 4060, install pain on Windows, and a short listening test. Licences and Korean support to be verified during the bake-off.
4. **Emotion transfer (2–3 days).** *Emotion labels built 2026-10-16 as the `emotion` stage (after `speakers`): every source sentence gets the tags heard in it — emotion, laughs/sighs/gasps/coughs, whisper, question — shown dashed in the editor for the reviewer to keep or untick (test-results C22). The detection works on acted English (82 % of emotion tags right at 0.9); its effect on the dub did not show in a machine listener, and Chatterbox's exaggeration did nothing measurable in Korean.* *Partly built 2026-10-15 as delivery transfer (no emotion labels): each dubbed sentence follows the original's loudness and pitch (test-results C20). Breaths copied from the original were tried and removed after listening: too loud, they stood out.* `express` stage + mapping from emotion label/intensity to whatever the chosen engine supports: CosyVoice instruction text ("speak sadly"), Chatterbox exaggeration value, Kokoro speed/gain only. Low-confidence emotions → neutral (a wrong emotion is worse than none).
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

### Product direction proposals (2026-10-14) — C11–C14

Decisions from the team: **no lip sync for now**; cloud GPUs (Nosana or similar) are acceptable, so local-only is no longer a requirement. Status below is "planned"; items marked **gated** need an instructor answer before any code is written.

#### C11. Doubtful parts coloured on the video timeline — **built 2026-10-14** (`report.timeline_html`, in report.html and the web page)
- **What:** under the dubbed video, a bar the length of the video with one block per sentence, coloured by its flag (translation / ASR / timing / OK); hover shows source and translation, click jumps the video there. Like YouTube's chapter segments, but coloured by doubt.
- **Where:** `report.html` (plain HTML5 `<video>` + a `<div>` bar, a few lines of JavaScript) and the same HTML in the web page.
- **Prerequisite — flag quality:** the bar only helps if flags mean something. Today: FLEURS 5/15 flagged (4 really wrong), en→ko 33/42 flagged (threshold too strict for that pair) — a mostly red bar is noise. Set thresholds **per language pair** on the gold set first (T-07).
- **Effort:** ~1 day. **Test:** block positions match segment times; clicking seeks; colours match `segments.json` flags.

#### C12. Cloud deployment (Nosana or similar) — planned
- **What:** run the same pipeline on a rented GPU instead of the user's machine. Nosana lists RTX 4090 at $0.40/h and A100 80 GB at $0.90/h (their page, 2026-10). Our measured speed is 26 s of processing per minute of video on an RTX 4060 → about **$0.003 per video minute** on a 4090 at that speed (4090 is faster, so this is an upper bound before overheads).
- **Steps:** (1) Docker image with ffmpeg and model weights baked in (~10 GB; otherwise every job downloads ~5 GB first), (2) job definition: input video URL → outputs uploaded to storage, (3) a small web front (the course's FastAPI template) that submits jobs and shows results, (4) keep `dubbe` runnable locally as the free path.
- **Costs to measure, not assume:** container start + model load time per job (dominates for short videos), storage/egress, idle time.
- **Risks:** Nosana hosts are third-party machines — uploading unpublished lectures there is a data-protection decision (Q-003, Q-012); the course provides no budget ("don't default to paying") — Baseline must stay runnable for free; the "runs locally" point in the competitor analysis becomes "can run locally or on cheap GPUs".
- **Effort:** ~1 week.

#### C13. Clone your own voice — **built 2026-10-15** (approved, Q-010; `web/clones.py`, Voices → Clone my voice)
- **As built:** live browser recording of three sentences picked at that moment (no uploads), valid 30 min; Whisper must hear them (CER ≤ 0.3, ≥ 8 s of voice); recording stored encrypted (Fernet, `DUBBE_VOICE_KEY`; without it cloning is off) and decrypted only for one job; engine Chatterbox Turbo (English) / Multilingual (Korean) with the recording as prompt; Perth watermark + AI label in the file comment. Tested 2026-10-15 with a synthetic stand-in (Kokoro bm_george): speaker similarity to the recording 0.96 (English) and 0.89 (Korean) vs 0.52–0.60 for the built-in voices (Chatterbox's voice encoder); check took 63 s.
- **Team decision 2026-10-14:** build it, with consent from the user for their own voice only. The course rule is unchanged, so instructor approval (Q-010) is still needed before it counts in the graded scope.
- **Conflict:** project tab Risk: "Voice cloning is out of scope … This applies even to your own team members' voices." Building this without written instructor approval risks the grade.
- **If approved, minimum safe design:** only the user's **own** voice; consent check before cloning — the user reads a random sentence on camera/mic, Whisper verifies the text, a speaker-similarity check verifies it is the same voice as the reference clip (ElevenLabs uses a similar "Voice Captcha"); every cloned dub carries the model watermark (Chatterbox embeds one by default) **and** a visible/audible "AI-dubbed voice" notice (Korea AI Basic Act, in force since 2026-01-22: realistic synthetic content needs a clear label); voice reference stored encrypted, deletable on request (voice can be biometric data under PIPA → separate consent).
- **Model:** Chatterbox Multilingual (MIT, Korean supported, watermark) or CosyVoice (Apache-2.0, Korean). Not XTTS-v2 (non-commercial licence). Added as one more engine in `tts.py`.
- **Does not solve multiple speakers.** Cloning decides *which voice*; diarization decides *who speaks when*. Multi-speaker still needs C7 (pyannote). Cloning the *other* people in a video means cloning people who did not consent — exactly what the course and the law restrict.
- **Effort:** ~1 week (engine 1 day, consent check 2 days, labelling 0.5 day, evaluation 1–2 days).

#### C15. Record your own voice for lines — planned (no cloning needed)
- **What:** for any sentence — typically lines of other people in the video, who never consented to being cloned — the user records the line with their own microphone; the recording replaces the synthesized audio for that sentence (`tts/<id>.wav`, `recorded: true` in `segments.json`) and goes through the same timing and mixing. ElevenLabs' Dubbing Studio has comparable voiceover tracks.
- **Why:** solves consent for third parties without cloning anyone; works with the course rule as it stands.
- **Limits:** manual work per line (defeats automation for long videos); still needs speaker detection (C7) to know which lines belong to whom; recordings are personal data → stay in `work/`, never in the repo.
- **Effort:** 1–2 days (record button per sentence in the web page, store, rerun from `timing`).

#### C16. Rate parts of the video on the timeline — **built 2026-10-14** (`ratings.py`, web page tab "Review & rate", `scripts/ratings_summary.py`); tested in a browser: click a block → video jumps + sentence selected; evaluation mode greys all flags
- **What:** click a sentence block on the coloured timeline (C11) → mark what is wrong (wrong meaning / wrong word / missing / mispronounced / cut off / timing) → score 0–100; saved to `ratings.json` per rater. This is the WMT human-evaluation method (Error Span Annotation, see [evaluation-research.md](evaluation-research.md)).
- **Evaluation mode:** flags **hidden** and a random sample of sentences — otherwise raters follow the flags and the ratings cannot test the flags (T-07).
- **Counts for the Baseline item only if** raters understand the target language, and ≥ 2 raters per sentence for reported numbers (agreement between raters is low even for experts).
- **Effort:** 2–3 days (needs the web page: a static `report.html` cannot save ratings).

#### C17. Error propagation with a teacher system — **built 2026-10-14** (`propagation.py`, `scripts/eval_propagation.py`); first run on FLEURS with the human reference, ElevenLabs reference still pending Q-013
- **Result (FLEURS ko→en, 12 sentences, chrF):** ASR CER 9.9 %; translation 49.4 as delivered vs 60.1 with the correct transcript → ASR errors cost **10.8 points**; translator alone 39.9 points from the human reference; TTS re-transcription WER **2.6 %**. Blame per sentence: 7 ok, 2 ASR, 2 translation, 1 both. Example: ASR "가나 안에는" for "가나안에는" → "Ghana" instead of Canaan. Limitation: chrF misses meaning errors ("below sea level" for "below freezing" scored ok) → add COMET / LLM judge next.
- **Teacher:** ElevenLabs dubbing API returns its source transcript and per-segment translation, so we get a teacher output **per stage**. Allowed for **evaluation only** — its Prohibited Use Policy forbids using output to train or fine-tune models.
- **Design:** oracle substitution — run A (all ours), B (teacher transcript → our translation), C (teacher transcript + teacher translation) → A vs B = our ASR's damage, B vs C = our translation's damage; TTS errors by re-transcribing our dub. Details in [evaluation-research.md](evaluation-research.md) §3.
- **Teacher ≠ truth:** validate the teacher on ~50 human-checked sentences first; otherwise report "agreement with ElevenLabs", not accuracy. Triangulate with reference-free metrics (MetricX-24-QE, CometKiwi) and an LLM judge with a fixed prompt.
- **Cost:** ElevenLabs automatic dubbing ≈ 3,000 credits/min → a 20–30 min test set fits one month of the Creator plan ($22, 121k credits). Course gives no budget and test clips would be uploaded to ElevenLabs (Q-013); opt out of ElevenLabs training on our data.
- **Effort:** ~1 week.

#### C18. Bigger or fine-tuned models — planned (after C17 measures where errors come from); the concrete plan is now C20
- **Bigger off-the-shelf first:** translation with an open LLM on a rented GPU (e.g. Gemma-3-27B fits one 80 GB GPU, ~$0.90/h on Nosana), compared on the same test set. WMT25 has no Korean–English human results, so measure, don't assume. Hunyuan-MT is excluded (licence excludes South Korea).
- **Fine-tuning only with a legal data source:** in-domain Korean–English pairs; commercial teacher output (ElevenLabs, most LLM APIs) is not allowed as training data. Open-weight teachers with permissive licences are.
- **Decide with C17's numbers:** improve the stage that causes most of the damage.

#### C19. Delivery tags per sentence ([whisper], [laugh], [slow] …) — **built 2026-10-14** (`tags.py`, Review tab)
- Reviewer ticks tags for a sentence → "Re-dub with my changes" re-runs from TTS with the same options. Timeline block shows ✦, tooltip lists tags.
- **Work with every voice and language (DUBBE applies them):** [slow] / [fast] (0.85× / 1.15× speed), [soft] / [loud] (−6 / +4 dB), [pause] (0.5 s before), [question] (forces a "?" ending → rising pitch). Tested: [slow] took a sentence from 7.22 s to 8.42 s.
- **Vocal tags need an expressive engine:** [whisper], [laugh], [sigh], [gasp], [cough], [excited], [sad], [angry]. Kokoro and MMS perform none → recorded as "not performed" in `segments.json`, the report and the page instead of being dropped silently.
- **Expressive engine — built 2026-10-15:** Chatterbox Turbo (MIT, English) in its own environment `.venv-chatterbox` (chatterbox-tts 0.1.7 pins torch 2.6.0, numpy < 2, transformers 5.2.0 — would break the main one), called by the `chatterbox` adapter in `tts.py` through `chatterbox_worker.py`; weights ~3.3 GB. Built-in voice only (no reference clip, no cloning); output carries Resemble's watermark. When an English video has a vocal tag the engine can do, the **whole** video switches to it (one voice per video); without the environment it stays on Kokoro and tags are "not performed". Tokens from its `added_tokens.json`: whisper→[whispering], laugh, sigh, gasp, cough, angry; no token for excited or sad. Measured on FLEURS (15 sentences): no tag read aloud as a word; [sigh] audible (Whisper hears "Huh."); [laugh] at the start lowers voiced frames 99 → 76–81 % (something non-speech, needs a listener), at the end nothing; **[whispering] is not a real whisper** (same sentence 98 % and 78 % voiced in two runs; a whisper is mostly unvoiced); TTS stage **122.9 s vs 6.5 s** with Kokoro. Korean vocal tags: only ElevenLabs v3 found (paid, external; Q-013). **Update 2026-10-15:** [whisper], [excited], [sad], [angry] and [question] are now made by DUBBE on the audio for every voice (C19b in test-results); Chatterbox is used only for [laugh], [sigh], [gasp], [cough].

#### C14. Voice marketplace — **built 2026-10-15 without payouts** (Q-011 under review; Voices page, admin tab "Voice clones")
- **As built:** owner opts in with a separate agreement → admin listens and lists or rejects → other users pick it in Text to Speech or a dub's editor (any language); owner can stop sharing at any time (no new uses), admin can take it out or delete it after a report; every use is counted (`voice_uses`) and the owner sees what they would earn at $0.03 / 1,000 characters. No payments, payouts, tax or licensing contracts.
- **Store front (`/app/market`, after Google Play / plugin marketplaces):** search (name, description, tags, publisher), filters by recording language and category (6), sort by popular / newest / top rated, featured row, voice cards with cover art and ratings, DUBBE originals row (the 27 presets); listing page per voice with sample, stats (rating, uses by others, added), description and tags, trust notes, "Get — add to my voices" (only added voices appear in the voice pickers), 1–5-star ratings with a histogram and reviews (one per user, only after getting it, not by the owner), more from the publisher; publishers write the listing (description, category, up to 3 tags) when they publish and can edit it.
- **Voice Studio (`/app/studio`, the publisher's console):** totals over all their voices (uses and adds by others, rating, would earn), each voice with a stepper Recorded → Checked → Listing → In review → Live; the voice page shows the check while it runs, then a listing editor with a live preview of the store card and the listing page, counters, at most 3 tags, Save draft / Publish, the admin's reason after a rejection, latest reviews. Recording a voice leads straight into it. Promotion: sidebar section with a "New" badge, a trending strip and a tile on the app home, "more voices" links next to the voice pickers, a teaser with the real count on the public home page. "Get" works in place (button turns into "Open", toast); the orb of a voice moves from its card to its page (cross-document View Transitions; off with reduced motion).
- **Reality check:** ElevenLabs already runs this (Voice Library: Professional Voice Clones shared after a voice check and manual review; owners paid ≈ $0.03 per 1,000 characters; ~$22M paid out in total; ~10,000 voices). A marketplace needs identity and consent verification, payments and payouts (e.g. Stripe Connect), tax handling, licensing terms, revocation/takedown, abuse moderation — none of which is graded AI work in this course, and all of it depends on C13 being allowed.
- **Proposal:** business-model slide + clickable mock-up + the consent/licensing rules written down; no build in this semester.

#### C20. Language quality upgrade — fine-tuned and distilled models for all languages, plus Uzbek — planned 2026-10-19 (decisions open)
- **Goal:** the best quality we can reach in all 22 languages and in Uzbek (not supported yet), measured, not assumed.
- **Where it runs — decided:** a rented GPU **by the hour, for training only**; DUBBE keeps running on our laptop (RTX 4060, 8 GB). Running DUBBE on a rented GPU all month (≈ $900–1,500/month for an always-on 80 GB GPU; ≈ half for a 48 GB one) is out of our budget. Consequence: every trained model must run in 8 GB — models run one stage at a time, so each stage may use the whole GPU.
- **Why not cut the "language part" out of a big model:** a model's skills are spread over all its weights; deleting parts breaks it. The working alternatives:
  1. **Translation-only models that already exist** (checked 2026-10-19 on Hugging Face; 4-bit versions ≈ 5 GB fit the laptop):

     | Model | Size | Korean | Uzbek | Licence (model card) |
     |---|---|---|---|---|
     | TranslateGemma (Google) | 4B / 12B | 55 languages, list not on the card — test | ? | Gemma terms |
     | Seed-X (ByteDance) | 7B | ✓ | ✗ | "other" — check |
     | Aya Expanse (Cohere) | 8B | ✓ | ✗ | CC BY-NC |
     | Tower-Plus (Unbabel) | 9B | ✓ | ✗ | CC BY-NC-SA |
     | NLLB (now) / MADLAD | 3.3B / 3–10B | ✓ | ✓ | CC BY-NC / Apache 2.0 |

     Hunyuan-MT stays excluded (licence excludes South Korea, C18).
  2. **Distillation:** a large open model, rented for hours, translates lecture and dialogue text with the conversation around each line (the "teacher"); the winning small model is fine-tuned on it (LoRA, the "student"). Teacher licences must allow it — not ElevenLabs or commercial APIs (C17, C18).
  3. **Vocabulary trimming:** drop the tokens of languages we do not use — smaller, same quality for ours.
  4. **4-bit compression** (GGUF via `llama-cpp-python`, one new dependency).
- **Phases:**

  | # | Phase | Where | Time |
  |---|---|---|---|
  | 0 | Translation shoot-out: the models above vs NLLB-3.3B on the 529 Korean–English pairs (test-results C23) and FLEURS for every language, with and without conversation context; quality, speed, memory. Uzbek baselines: Whisper vs two Uzbek fine-tunes (`hostmepanda/whisper-large-v3-turbo-uzbek-ct2`, MIT; `navai-uz/whisper-medium-uzbek`, Apache 2.0), NLLB / MADLAD en↔uz, available Uzbek voices | laptop, free | 2–3 days |
  | 1 | Translation distillation for all our pairs incl. Uzbek; LoRA on the Phase 0 winner; 4-bit; measured again | rented, ~20–40 GPU-h | 3–4 days |
  | 2 | Recognition: fine-tune Whisper where it is weak (test-results C23, C25): Uzbek, Swahili 26 %, Turkish 17 %, Hindi 13 %, Korean conversation 11.5 %, Malay 10 %, Chinese 9 %, Japanese 7 %, Hebrew 29 % (to bring it back). Kept only if it beats the base model on held-out data (the Korean fine-tune we tried was 3× worse) | rented, ~20–40 GPU-h | 3–5 days |
  | 3 | Voices: fine-tune Chatterbox Multilingual per language, in order of need — Uzbek (no voice yet), Hebrew (needs `dicta_onnx`), Japanese 9.6 %, Swahili 6.6 %, Hindi 6.0 %, Greek 6.0 %, Polish 5.4 %, then Korean for naturalness | rented, ~40–80 GPU-h | 1–2 weeks |
  | 4 | Proof on the laptop: real dubs per upgraded language, native-listener tests, test results, site texts | laptop | 3–4 days |

  GPU: one RTX 4090 (24 GB, roughly $0.3–0.7/h) for most training; an A100 80 GB (roughly $1–2/h) only for a few hours if the teacher is large. Total ≈ 100–200 GPU-hours ≈ **$50–300 once** (prices to check when renting). ≈ 3–4 weeks of calendar time.
- **Uzbek:** Whisper and NLLB (`uzn_Latn`) already cover it; Chatterbox does not. Voice options: (a) `Tohirju/chatterbox-mtl-uzbek` — a Chatterbox Multilingual fine-tune (MIT, gated: needs a Hugging Face account and an access request; its card claims 14.8 % median word errors on FLEURS-uz with its own recogniser, uses the Turkish language token; 0 downloads — verify); (b) Meta MMS-TTS Uzbek (one robotic voice, Cyrillic only, CC BY-NC); (c) our own Chatterbox fine-tune with a real Uzbek token and letters (oʻ gʻ). Training data: ISSAI Uzbek Speech Corpus (MIT, ≈ 9.5 GB; a CC BY 4.0 copy has 100,767 training utterances), Common Voice Uzbek (CC0, from Mozilla), FLEURS-uz (CC BY 4.0, test split held out); YouTube-sourced sets are left out (rights of the audio unclear). For the best voice: 3–5 h of clean recordings from each of 2–4 consenting native speakers, with written consent (training on a voice is cloning, same rules as C13).
- **Rules:** only public datasets and consented recordings go to a rented machine — never users' videos or clones; trained models stay non-commercial (NLLB licence); every result measured on held-out tests against Phase 0 and kept only if better; "best" claimed only where native listeners confirmed it — automatic checks (Whisper round trip, speaker similarity, a naturalness score) elsewhere; no audio or data in the repo.
- **Decisions open:** start Phase 0; Uzbek recordings yes/no and who; which languages have native listeners; instructor approval for training on a rented GPU and for the recordings (Q-014).

---

## Phase D — Stretch (only if chosen Target items are done)

- Larger human watchability study.
- Qwen3 vs. NLLB comparison on the gold set.
- Fine-tuning / distillation — only with instructor approval; plan in C20 (Q-014).
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
