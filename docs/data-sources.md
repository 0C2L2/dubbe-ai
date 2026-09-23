# DUBBE — Data Sources (draft v1, 2026-09-23)

Owner: Data & Research (Samandarov Madina). Items marked **TBD** are not selected or not yet confirmed.

## Rules we follow

From the course ground rules and project tab C2b:

- Only openly licensed video or video the team records with documented consent. No personal, customer, or company data.
- **No video or audio files in the public repository** — not even with consent. We publish the source URL and how to reproduce, not the file.
- Openly licensed does not automatically allow publishing a modified version. **Dubbing is a derivative work**, so any licence with *No Derivatives* (ND, 변경금지) is rejected.
- No voice cloning of anyone, including team members.
- Every clip gets an entry in the [inventory](#clip-inventory) below and in the README before it is used.

## 1. Source videos (pipeline input)

| Source | Licence | Use | Access | Status |
|---|---|---|---|---|
| [KOCW](http://www.kocw.net) — Korea OpenCourseWare university lectures | **Varies per course** (CC licence shown on each lecture page) | Main test input: real Korean lecture speech, single speaker, slides | Public, no login | Selecting clips; accept only BY, BY-SA, BY-NC, BY-NC-SA — **reject ND** |
| [K-MOOC](https://www.kmooc.kr) courses | Varies per course, often more restrictive | Backup input | Account needed | TBD — check terms before use |
| YouTube videos filtered to *Creative Commons* | CC BY | Backup input, varied speakers | Public | TBD |
| Clips recorded by the team | Own; written consent from everyone recorded | Hard cases on demand: fast speech, hesitations and restarts, English terms mixed into Korean, numbers and formulas, two speakers (Target: multi-speaker) | Team | TBD — consent form first; files stay on a private team drive |

**Clip plan (initial):** 3 KOCW clips of 3–5 min (e.g. one humanities, one engineering/CS, one with dense slides) + 2 team-recorded clips of 2–3 min. Short clips first, as the tab advises.

## 2. Evaluation data (for the test plan)

| Dataset | What it gives us | Licence | Access | Status |
|---|---|---|---|---|
| **Team gold set** — human Korean transcript + human English translation of ~20 min of the clips above | Reference for ASR CER, translation quality, and the error-propagation study (Target) | Ours (derived from the clip's licence) | Created by the team | TBD — IBT members transcribe/translate, a second member checks |
| [FLEURS](https://huggingface.co/datasets/google/fleurs) — Korean (`ko_kr`) test split | Read Korean speech with transcripts; the same sentences exist in English (`en_us`), so it provides free KO audio → EN reference pairs | CC BY 4.0 | Public, Hugging Face | Planned as a quick sanity benchmark before the gold set is ready; read speech, not lecture speech |
| Rating sheets from English-speaking reviewers | Human judgement of adequacy, fluency, sync, watchability | Ours | Team + TBD international students (Q-007) | Rubric in [test-plan.md](test-plan.md); no names stored, raters are R1, R2, … |

## 3. Pretrained models (not data we collect, but their licences apply)

| Model | Stage | Licence | Note |
|---|---|---|---|
| Whisper large-v3-turbo via faster-whisper / WhisperX | ASR | MIT (weights), BSD-2 (WhisperX) | |
| kresnik/wav2vec2-large-xlsr-korean | Word alignment (WhisperX default for Korean) | TBD — verify on model card | |
| NLLB-200 distilled-600M | Translation | **CC BY-NC 4.0** | Non-commercial only — fine for the capstone, but a commercial product would need another MT model. Stated in the cost comparison. |
| Kokoro-82M | TTS (preset voices) | Apache 2.0 | |
| Unbabel wmt22-cometkiwi-da / BLASER 2.0-QE (Target) | Quality estimation | CC BY-NC-SA 4.0 / TBD | CometKiwi is gated: accept terms on Hugging Face |

## Clip inventory

Filled in as clips are selected. Mirrored in the README data table.

| ID | Title / source URL | Licence | Collected | Length | Personal data | Preprocessing | Publishable dubbed demo? |
|---|---|---|---|---|---|---|---|
| C01 | TBD (KOCW) | | | | Lecturer's voice and possibly face — public lecture, not redistributed | Trim to selected minutes; 16 kHz mono WAV | Only if not ND and share-alike terms can be met |
| C02 | TBD (KOCW) | | | | | | |
| C03 | TBD (KOCW) | | | | | | |
| T01 | Team recording | Own | | | Team member voice/face, consent on file | Same | No (consent ≠ permanent publication) |
| T02 | Team recording | Own | | | | | No |

## How to reproduce

1. Open the source URL in the inventory, download the lecture, and trim to the listed time range (exact ffmpeg command will be in the README once the pipeline runs).
2. FLEURS: `datasets.load_dataset("google/fleurs", "ko_kr", split="test")`.
3. Team recordings and the gold set are shared with instructors on request; they are not public.

## Open questions

Q-002 (publishing a dubbed KOCW clip), Q-007 (who can rate) — see [questions.md](questions.md).
