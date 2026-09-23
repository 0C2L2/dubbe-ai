# DUBBE — Project Overview (draft v1, 2026-09-20)

**Project tab:** C2b – Video Translation and Dubbing, *HBAI Capstone Project Pool* (Inha University × HumbleBeeAI, Fall 2026). Problem statement, Definition of Done, and resource list are inherited from that tab and credited here.

**Status:** initial draft. Items marked **TBD** are undecided; see [questions.md](questions.md).

## 1. Problem

Educational video is recorded in one language, but many of the people who need it don't speak that language well. Korean universities record lectures in Korean while international enrollment grows. Online course creators can only sell into the language they filmed in. Either way, useful video reaches a fraction of its intended audience.

The existing options don't close the gap:

- **Subtitles** compete with the screen. You cannot read them and follow a diagram at the same time, which is exactly when the content matters most.
- **Professional dubbing** is accurate but priced per minute (translators, voice actors, studio time), so it is never justified for hundreds of hours of routine course material.
- **Automated dubbing tools** (YouTube auto-dub, ElevenLabs, HeyGen, Rask) return a finished file with no indication of what went wrong, so the user cannot tell which parts to trust.

## 2. Target users

**Buyer (chosen from the three in the project tab): online course creators and small edtech companies.** They want to sell into new language markets, decide quickly, and are priced out of professional dubbing entirely. They are not saving money on an existing process; they are getting access to something they could not afford at all. Value is measured against the per-minute price of the alternative.

Adjacent segments, in order of later interest:

1. Universities with international students — large archives of Korean lectures, growing non-Korean enrollment, slow procurement.
2. Corporate L&D at multinationals — largest budgets, demands human QA.
3. SMEs employing migrant workers (safety/onboarding training) and public agencies producing information videos for foreign residents.

## 3. How users solve it today

Subtitles (cheap, fails on visual content), professional dubbing (~$15–75/min, rarely justified), or a commercial AI dubbing tool (ElevenLabs $0.33–2.20/min, HeyGen ~$24/mo, Rask ~$2.40/min) with no way to know which sentences are wrong. Interview plan: **TBD** (course creators / international students at Inha).

## 4. Proposed solution

DUBBE converts a source video into a dubbed version through a connected pipeline:

```
Video → ASR (word-level timestamps) → Sentence Segmentation → Translation → TTS → Timing → Dubbed Video
```

Speech recognition transcribes the original audio with per-word timing. Segmentation groups words into translatable sentences. Translation converts them, text-to-speech generates the new voice track with a **preset voice (no voice cloning)**, and the timing stage fits that audio back to the video without drifting over the length of a clip.

**What makes it distinct: a second output, the quality report.** Errors in a chained pipeline compound: one misheard word becomes a confident translation error, then fluent synthesized speech that says something wrong — and sounds more trustworthy than it is. DUBBE records a confidence signal at every stage, traces error through the chain, shows which stage contributes most to final quality loss, and flags the segments a human should review.

The deliverable is therefore not a finished dubbed video but **a usable draft plus a short review list**. For educational content that is the right goal: cut the localization work substantially rather than remove the human entirely.

## 5. Inputs and outputs

| | |
|---|---|
| **Input** | One video file (MP4), source language = Korean, single speaker, 2–10 minutes |
| **Output 1** | `dubbed.mp4` — same video, English synthesized voice track |
| **Output 2** | `segments.json` — per sentence: source text, translation, timestamps, ASR confidence, translation quality estimate, time-stretch factor, review flag |
| **Output 3** | `report.html` (Target) — the segments a human should check, and a per-stage breakdown of where quality dropped |

Every AI-generated output a user sees (transcript, translation) is editable in `segments.json`; a segment can be re-synthesized after editing. **Exact review UI: TBD** (Q-006).

## 6. Definition of Done and our plan

Tiers are copied from the project tab. "Plan" is ours.

### Baseline (build first, completely)

| Item | Plan |
|---|---|
| Full pipeline end to end: extract audio, ASR with word-level timestamps, group into sentences, translate, synthesize, adjust timing, merge into video | One CLI command `dubbe input.mp4` that runs 7 stages, each writing a file to `work/` so any stage can be inspected or re-run |
| Watchable dubbed video for at least one language pair | Korean → English |
| Timing stays acceptable across a several-minute clip, no progressive drift | Anchor each segment to its **source** start time; per-segment stretch within 0.8×–1.3×; overflow spills into the following pause rather than shifting later segments |
| Output quality assessed by someone who speaks the target language | English rating by team members + **TBD** international students; rubric owned by Data & Research |

### Target

| Item | Plan |
|---|---|
| Error propagation measured: where does quality break down, how much does each stage contribute | Gold set (~20 min, human KO transcript + human EN translation). Compare: ASR CER; translation quality (reference-free QE) on gold transcript vs. on ASR transcript; stretch factor per segment. The deltas isolate each stage's contribution |
| Timing when translation is substantially longer/shorter | Beyond 1.3×: ask the translator for a shorter rendering (length-aware prompt) — **TBD** whether this needs an LLM |
| A second language pair | **TBD** — must be a language a teammate can evaluate (Q-005) |
| Multiple speakers distinguished | WhisperX diarization → one preset voice per speaker |
| Cost per minute vs. professional dubbing, with honest quality statement | Our compute cost (free Colab ≈ $0, or rented GPU-hour) vs. ElevenLabs $0.33–2.20/min and human dubbing; quality gap from the rating study |

### Stretch (only after all Baseline items are done)

Human watchability evaluation. **Left out:** voice-characteristic preservation and lip-sync-aware timing (voice cloning is out of scope per the tab; lectures are off-screen narration so lip sync adds little).

## 7. Data sources

| Source | Licence | Access | Notes |
|---|---|---|---|
| KOCW (Korea OpenCourseWare) lectures | Varies per course (CC) | Public, **not yet selected** | Dubbing is a derivative: reject No-Derivatives (ND) courses; share-alike terms apply to any published dubbed clip. Details in [data-sources.md](data-sources.md) |
| K-MOOC / university YouTube channels filtered to CC-BY | CC BY | Public, **TBD** | |
| Short instructional clips recorded by the team | Own, written consent from everyone recorded | **TBD** | Recommended by the tab: we control content and can include hard cases |
| AI Hub Korean speech datasets | Korean-ID registration, training-only clauses | **Likely inaccessible** | Not planned |

Video and audio files are **never committed** to the repository; the README records URL, licence, date, personal-data check, and preprocessing for each clip.

## 8. Tools, models, free path, hardware

| Stage | Free / open choice | Fallback |
|---|---|---|
| Extract / mux | ffmpeg | — |
| ASR + word timestamps | WhisperX (faster-whisper large-v3-turbo + forced alignment) | whisper-timestamped |
| Segmentation | Whisper segments + Korean sentence enders + pause length (`kss` library) | — |
| Translation | NLLB-200 distilled-600M (runs on Colab / CPU) | NLLB 1.3B if quality is insufficient; LLM only if permitted (Q-003) |
| TTS (preset voices) | Kokoro-82M (Apache 2.0, CPU) | Coqui XTTS-v2 preset voices (tab suggestion), Piper |
| Timing | ffmpeg `atempo` + TTS speed parameter | — |
| Quality estimate (Target) | CometKiwi-22 or BLASER 2.0-QE (reference-free) | back-translation similarity |

**Hardware:** Baseline must run without a dedicated GPU or paid API (project tab, Risk). Plan: Google Colab free tier; CPU for TTS. To be confirmed in Weeks 2–3 (Q-004).

**Starter template:** [humblebeeai/module-python-template](https://github.com/humblebeeai/module-python-template) — DUBBE is a batch CLI pipeline; no HTTP API or database is needed.

## 9. Technical difficulties to investigate first

In order (from the tab's *Known hard parts*):

1. **Environment** — confirm ffmpeg + WhisperX + NLLB + TTS run end to end on one 2-minute clip in Colab free tier. Week 2–3.
2. **Sentence grouping** — turning word timestamps into translatable sentences when speech has hesitations and restarts. Directly determines translation quality.
3. **Timing mismatch** — Korean → English length ratio per sentence; decide the overflow rule and accept the trade-off.
4. **Invisible degradation** — synthesized speech sounds fluent whether or not the translation is right; evaluation must be by English speakers, planned early.
5. **Reliable structured output** from the translation stage (only an issue if an LLM is used).

## 10. References

- HBAI Capstone Project Pool, tab C2b "Video Translation and Dubbing" — problem, DoD, resources
- WhisperX: Bain et al., *Time-Accurate Speech Transcription of Long-Form Audio*, 2023 — https://github.com/m-bain/whisperx
- NLLB-200: Meta AI, *No Language Left Behind*, 2022 — https://arxiv.org/abs/2207.04672
- Kokoro-82M TTS — https://huggingface.co/hexgrad/Kokoro-82M
- BLASER 2.0-QE — https://huggingface.co/facebook/blaser-2.0-qe
- Brannon et al., *Dubbing in Practice: A Large Scale Study of Human Localization*, 2022 — https://arxiv.org/abs/2212.12137 (humans do not enforce strict isochrony)
- Subramanian et al., *Length Aware Speech Translation for Video Dubbing*, Interspeech 2025 — https://arxiv.org/abs/2506.00740
- ElevenLabs Dubbing API pricing (cost comparison point)
- Existing open-source pipelines for comparison: pyVideoTrans, SoniTranslate
