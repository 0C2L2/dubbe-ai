# DUBBE

### AI-Powered Video Translation & Dubbing

**DUBBE** turns a lecture or course video recorded in one language into a dubbed version in another — and tells you which sentences to double-check.

```
Video → ASR (word timestamps) → Sentence Segmentation → Translation → TTS → Timing → Dubbed Video
```

Every stage of a dubbing pipeline is a model, and errors compound: a misheard word becomes a confident mistranslation, then fluent synthesized speech that says something wrong. DUBBE's second output is a **quality report** that traces confidence through the chain and flags the segments a human should review. The result is a usable draft plus a short review list, not a black-box video.

**Applied AI & Business Capstone Design** · Inha University × HumbleBeeAI · Fall 2026 · Team 1 · Project tab **C2b – Video Translation and Dubbing**

## Architecture

![DUBBE main architecture](docs/diagrams/architecture-overview.png)

Details: [docs/architecture.md](docs/architecture.md) (C4 Level 1 and 2, pipeline flow, [model per task](docs/architecture.md#model-per-task): each stage uses a model built for its job, swappable in `languages.yaml`).

## Documents

- [Project overview](docs/project-overview.md) — problem, users, solution, Definition of Done and our plan, data, tools
- [Technical build plan](docs/project-plan.md) - step-by-step: stack, repo layout, data formats, each stage with commands and checks
- [Evaluation research](docs/evaluation-research.md) — human ratings on the timeline, "teacher" references, error propagation: what the papers say
- [Website plan](docs/website-plan.md) — site map, public pages (home, plans, contact, FAQ, legal), sign-in, app, admin, architecture, phases (weeks 7–14), decisions needed
- [Competitor analysis](docs/competitors.md) — ElevenLabs, HeyGen, Rask, YouTube, Perso and others: features, price per minute, where DUBBE differs
- [Team roles and responsibilities](docs/team.md)
- [Question log](docs/questions.md) — open questions for instructors and mentors
- [Architecture — C4 Level 1 and 2](docs/architecture.md)
- [Data sources](docs/data-sources.md) — clips, licences, evaluation data, model licences
- [Test plan](docs/test-plan.md) — how each Definition of Done item is checked
- [Test results](docs/test-results.md) — what has actually been measured so far
- [Knowledge base](docs/rag-knowledge-base.md) — the whole project in self-contained paragraphs, for retrieval (RAG)
- Ground rules, functional requirements — TBD

## Features and status (2026-11-03)

Tiers follow the project tab's Definition of Done. ✅ built and tested · 🟡 built, partly tested · ⬜ not started. Measured results: [docs/test-results.md](docs/test-results.md).

**Baseline**
- ✅ One command runs the whole pipeline: extract → separate → speech recognition with word timestamps → sentences → translation → speech synthesis (preset voice, no cloning) → timing → video
- ✅ Korean → English dub (tested on FLEURS read speech and a private TV clip)
- ✅ No progressive timing drift (drift check passes on all test clips)
- ⬜ Output quality rated by English speakers (needs raters, Q-007)

**Target**
- 🟡 Error propagation: review flags per stage built (`report.html`); the gold-set study (T-05/T-06) not started
- ✅ Long translations: shorter alternative wording + optional picture slow-down (`--slow-video 1.2`)
- 🟡 Uzbek and Kazakh, with free models (test results C43): Uzbek recognition by **rubaistt v2 medium** (Apache-2.0, 2.3–3.5 % CER vs 25 % for Whisper), voice **Navoiy TTS** (Apache-2.0, on CosyVoice 2 in `.venv-cosyvoice`; clones and acts 7 emotion tags); Kazakh voice **Piper ISSAI** (MIT, CPU, 6 voices, no cloning). FLEURS read speech, 12 sentences each way: chrF++ 53–59, dub heard back 0–11 % off
- 🟡 24 languages, any pair (test results C25, C43): Korean ↔ English tested in depth; Arabic, Chinese, Danish, Dutch, Finnish, French, German, Greek, Hindi, Italian, Japanese, Malay, Norwegian, Polish, Portuguese, Russian, Spanish, Swahili, Swedish, Turkish only on read speech (FLEURS) — recognition weak for Swahili, Turkish, Hindi; Hebrew left out
- 🟡 Second language pair: English → Korean runs (Ming-3.0-tts + CosyVoice 3; Chatterbox Multilingual, then MMS, when their environments are missing); needs a fluent Korean rater and approval (Q-005)
- 🟡 Multiple speakers: detected per sentence by voice, each speaker their own voice, transcripts by speaker; the reviewer renames, merges or splits speakers — similar voices get merged (test results C21). Speaker diarization from the audio, before speech recognition: **NVIDIA Nemotron 3 Diarization** finds the speaker turns, then **TitaNet** voice fingerprints group the turns by voice from scratch (both in `.venv-nemo`) — 12 of 12 known voices, 3 of 3 similar women and 4 of 4 voices right, no 8-speaker limit (test results C31); speech recognition then runs per speaker turn, so sentences never mix two people and interview clips are no longer skipped (C29). Without `.venv-nemo` it falls back to per-sentence WavLM fingerprints. Step 6 (`speakers`) then decides who said each word, splits a sentence two people share (also a mid-sentence hand-over, checked by voice), flags doubtful sentences and asks when two speakers may be one person (C33); on a hand-labelled real news clip 20 of 20 sentences and 6 of 6 people were right (C34). The Speaker Detection page shows each speaker as a painted orb (play their voice, rename, clone with consent, merge when asked) above per-speaker lanes and the transcript next to the original video (a line or a lane plays from there); **Fix speakers** lets a person move words between speakers with a word-high bar at the start of each line (drag or ← →), start a new line from a word, or give a line to another speaker — every word is kept exactly once, and a fixed result is never overwritten by a re-run
- 🟡 Cost per minute vs. professional dubbing: computed for every run (`stats.json`, report, web page); price assumptions in `languages.yaml` still need sources

**Stretch / beyond the DoD**
- ✅ Background sound kept (music, effects, a phone ringing) under the new voice
- 🟡 Voice matching: preset voice chosen by the speaker's pitch register (per speaker; reviewer can override); Korean dubs choose from 26 voices — the built-in one and 25 English presets speaking Korean (test results C24)
- 🟡 Expressive voice: reviewer delivery tags per sentence ([slow], [question], [whisper], [excited], [sad] … made by DUBBE, any voice — [question] switches English to Chatterbox, whose end rose in 11 of 12; [laugh], [sigh], [gasp], [cough] English only via Chatterbox and weak, Korean cannot — see test results); tags heard in the original are put on each sentence automatically (emotion, laugh / sigh / gasp / cough, whisper, question — dashed in the editor, the reviewer unticks wrong ones); the emotion effects did not measurably change the dub yet (test results C22, [plan C9](docs/project-plan.md)). Expression transfer is approved (Q-009); Korean and English speak with **Ming-3.0-tts** (MIT, `.venv-ming`), which acts [excited], [sad], [angry], [scared], [surprised], [disgusted] itself; **CosyVoice 3** (Apache-2.0, `.venv-cosyvoice`) speaks [sympathetic] (beyond Ming's 7 emotions), the plain Korean sentences, and says again every sentence Whisper hears more than 5 % off - the better take stays (test results C35–C38)
- 🟡 Natural delivery: each dubbed sentence follows the original's loudness and pitch, fades and a soft limiter (test results C20; needs a listening test)
- ✅ Voice cloning of **your own voice** (approved, Q-010): live recording of sentences picked at that moment, Whisper check, encrypted storage (`DUBBE_VOICE_KEY`), watermark + AI label; voice **Marketplace** (store front with search, categories, sorting, ratings and reviews; get a voice to use it; admin review; no payouts) and a **Voice Studio** for publishers (progress from recording to live, listing editor with live preview, uses / rating / "would earn"); a speaker **from the video** only with the uploader's consent, kept encrypted inside that project (plan C13/C14, C7)
- 🟡 Website (`dubbe-web`): public pages, accounts, plans and limits, upload → background job → review editor → downloads (MP4, SRT/VTT, report), contact — runs locally, tested end to end; not deployed yet
  - **Subtitles** (service): captions coloured by speaker (white, yellow, cyan, green …) as SRT / WebVTT / ASS, named speakers, optional translation, burned into the video on request; a dub's captions the same way (Download → Make the video with captions)
  - User app with a sidebar: home dashboard (usage, quick actions, recent work), Dubbing, **Text to Speech** (tags typed into the text, e.g. `[slow]`, `[question]`, `[laugh]`), **Speech to Text** (transcript + subtitles, optional translation), **Speaker Detection** (who speaks when, transcript and subtitles by speaker with names, clone a speaker into your voices with consent — private, never published), **Translate** (per-sentence confidence and alternatives), **Voice Isolator** (voice and background stems), History, Voice library — every tool runs the pipeline's own stages as a queued GPU job
  - Admin dashboard: overview (key numbers, jobs per day, worker), users (plan, admin rights, delete), jobs and tool jobs with retry, messages, evaluation; accounts via `python scripts/create_user.py EMAIL [--admin]`
- Out of scope: lip sync

## Project structure

```
src/dubbe/          pipeline: one module per stage + cli.py, languages.yaml (all language settings)
src/dubbe/web/      the website (FastAPI + SQLite + HTML templates): runs the pipeline as background jobs
tests/              unit tests for the logic that is easy to get wrong (pytest)
scripts/            test clip builder and the T-03 / T-12 / T-14 check scripts
docs/               overview, plan, architecture (C4), data sources, test plan and results, diagrams
data/  work/        local only (git-ignored): test videos, intermediate files and outputs
course/  archive/   local only (git-ignored): course PDFs, superseded drafts
```

## Team

| Member | Major | Role |
|---|---|---|
| Kalandarov Ulugbek | IBT | Team Representative / PM |
| Isokulov Azamat | IBT | Problem & Business |
| Samandarova Madina | IBT | Data & Research, User & Requirements |
| Musurmonov Jakhongir | IBT | Demo & Presentation |
| Tagaev Rashid | ISE | AI / Technical Lead |
| Kholmirzaev Temurjon | ISE | Software / IT Engineer |

Details in [docs/team.md](docs/team.md).

## Tech stack (all free, run locally)

ffmpeg · faster-whisper (Whisper large-v3 for Korean, large-v3-turbo for English) · NLLB-200 3.3B (int8, CTranslate2) · Kokoro-82M · Chatterbox (Turbo and Multilingual, optional environment; MMS-TTS as Korean fallback) · Demucs · NVIDIA Nemotron 3 Diarization + TitaNet-large · WavLM speaker verification (fallback) · Ming-3.0-tts 0.5B + CosyVoice 3 (Korean and English voices, optional environments) · emotion2vec+ large (emotions heard in the original) + AST AudioSet (sounds) · Python 3.10–3.12

Starter template: [humblebeeai/module-python-template](https://github.com/humblebeeai/module-python-template) — chosen because the core of DUBBE is a batch command-line pipeline. The website (`src/dubbe/web/`) adds FastAPI, SQLite and HTML templates on top of it; plan: [docs/website-plan.md](docs/website-plan.md).

## Data

No video or audio files are stored in this repository. Full plan and licence rules in [docs/data-sources.md](docs/data-sources.md). Each test clip will be listed here with its source URL, licence, collection date, personal-data check, and preprocessing.

| Clip | Source | Licence | Date | Personal data | Preprocessing |
|---|---|---|---|---|---|
| FLEURS ko_kr dev, 12 sentences (`scripts/make_fleurs_clip.py`) | huggingface.co/datasets/google/fleurs | CC BY 4.0 | 2026-10-05 | Read speech by volunteers, published dataset | Concatenated with 1 s pauses, slides drawn with the text |
| Lecture clips | KOCW / K-MOOC / team-recorded (with consent) | Per clip; No-Derivatives licences rejected | TBD | | |

## Setup and run

Status: runs end to end on a local NVIDIA GPU (RTX 4060, 8 GB). Not yet tested from a fresh clone on a second machine (T-01) or on Colab (Q-004).

Requirements: ffmpeg on PATH; **Python 3.10–3.12** (Kokoro needs < 3.13); NVIDIA GPU recommended (CPU works, slower). First run downloads ~5 GB of model weights.

```bash
py -3.12 -m venv .venv && .venv/Scripts/activate   # Linux/macOS: python3.12 -m venv .venv && source .venv/bin/activate
# GPU: install CUDA PyTorch first (the default Windows torch is CPU-only); skip this line for CPU-only
pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[models,gui,eval,dev,web]"
dubbe-web                                       # the website at http://127.0.0.1:8000: public pages, sign-up, upload,
                                                # progress, review editor, downloads, admin (settings: .env.example;
                                                # without SMTP, sign-up mails land in data/web/outbox/)
python scripts/make_voice_samples.py            # once: audio for the site's voice carousel (data/web/samples, git-ignored)
dubbe-gui                                       # simplest way to try it: local web page at http://127.0.0.1:7860
                                                # tab 'Review & rate': coloured timeline of doubtful parts, rate each sentence
                                                # ...and add delivery tags per sentence ([slow], [question], [whisper] ...), then re-dub
# recommended: the Korean voice and English vocal tags ([laugh] [sigh] [gasp] [cough]) use Chatterbox in its own
# environment (it pins torch 2.6 / numpy < 2); built-in voices only. Without it Korean falls back to MMS-TTS (non-commercial)
# and English vocal tags are "not performed". First use downloads ~3 GB (Multilingual) and the Turbo weights
py -3.12 -m venv .venv-chatterbox
.venv-chatterbox/Scripts/python -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
.venv-chatterbox/Scripts/python -m pip install chatterbox-tts==0.1.7
# voice cloning (your own voice): needs the Chatterbox environment above and DUBBE_VOICE_KEY set in the environment
# (make one: see .env.example). Recordings are encrypted with it; if the key is lost they cannot be read again
# speaker diarization (default engine): Nemotron 3 runs in its own environment with NeMo from GitHub (its rotary
# attention is not in the pip release yet). Without .venv-nemo, speakers are found per sentence by WavLM instead
py -3.12 -m venv .venv-nemo
.venv-nemo/Scripts/python -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
.venv-nemo/Scripts/python -m pip install Cython packaging
.venv-nemo/Scripts/python -m pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA-NeMo/Speech.git"
# Korean and English voices: Ming-3.0-tts (emotions) with CosyVoice 3 (more emotions, Korean plain lines, retries), each in
# its own environment with its code checked out next to them. Without them Korean / English use Chatterbox / Kokoro
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git .cosyvoice
py -3.12 -m venv .venv-cosyvoice
.venv-cosyvoice/Scripts/python -m pip install -r .cosyvoice/requirements.txt   # torch 2.3.1; first use downloads ~5 GB
git clone --depth 1 https://github.com/inclusionAI/Ming-3.0-tts.git .ming
py -3.12 -m venv .venv-ming
.venv-ming/Scripts/python -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
.venv-ming/Scripts/python -m pip install -r .ming/requirements.txt              # first use downloads ~3 GB
# Uzbek uses .venv-cosyvoice too (Navoiy: CosyVoice2-0.5B + 1.9 GB of weights, ~6 GB on first use); Kazakh's Piper is in
# the models extra. Uzbek recognition (rubaistt) is converted for faster-whisper on first use (~1.5 GB)
python scripts/ratings_summary.py work/lecture.ko-en                          # scores, flag precision/recall, rater agreement
python scripts/eval_propagation.py work/lecture.ko-en reference.json          # which stage causes the errors (C17)
pytest                                          # unit tests: sentence grouping, timing
dubbe lecture.mp4 --src ko --tgt en             # -> work/lecture.ko-en/dubbed.mp4
                                                # + report.html: segments a human should check, and why
                                                # music/effects are kept under the new voice; --no-background = voice only
python scripts/background_check.py              # T-12: phone ring survives, no original voice leaks
python scripts/drift_check.py work/lecture.ko-en/segments.json   # T-03: timing drift PASS/FAIL
python scripts/make_fleurs_clip.py              # optional: Korean test clip with reference text (FLEURS, CC BY 4.0)
```

Every stage writes its result into `work/<video>.<src>-<tgt>/`. To correct a translation, edit `tgt_text` in `segments.json`, set `"edited": true`, and run `dubbe lecture.mp4 --from tts`.

## Credits

Problem statement and Definition of Done are from the HBAI Capstone Project Pool, tab C2b. Third-party models and their licences are listed in [docs/project-overview.md](docs/project-overview.md#8-tools-models-free-path-hardware). The emotion tags use emotion2vec+ large by Alibaba DAMO Academy / [FunASR](https://github.com/modelscope/FunASR) (FunASR model license). Live Dubbing (beta) reads links with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) and plays the delayed stream with [hls.js](https://github.com/video-dev/hls.js) (Apache-2.0, served from `web/static/vendor`). AI tools (Claude) were used to write code and documentation; the team reviewed and tested it.
