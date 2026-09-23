# DUBBE

### AI-Powered Video Translation & Dubbing

**DUBBE** turns a lecture or course video recorded in one language into a dubbed version in another — and tells you which sentences to double-check.

```
Video → ASR (word timestamps) → Sentence Segmentation → Translation → TTS → Timing → Dubbed Video
```

Every stage of a dubbing pipeline is a model, and errors compound: a misheard word becomes a confident mistranslation, then fluent synthesized speech that says something wrong. DUBBE's second output is a **quality report** that traces confidence through the chain and flags the segments a human should review. The result is a usable draft plus a short review list, not a black-box video.

**Applied AI & Business Capstone Design** · Inha University × HumbleBeeAI · Fall 2026 · Team 1 · Project tab **C2b – Video Translation and Dubbing**

## Documents

- [Project overview](docs/project-overview.md) — problem, users, solution, Definition of Done and our plan, data, tools
- [Team roles and responsibilities](docs/team.md)
- [Question log](docs/questions.md) — open questions for instructors and mentors
- [Architecture — C4 Level 1 and 2](docs/architecture.md)
- [Data sources](docs/data-sources.md) — clips, licences, evaluation data, model licences
- [Test plan](docs/test-plan.md) — how each Definition of Done item is checked
- Ground rules, functional requirements — TBD

## Planned features

Tiers follow the project tab's Definition of Done.

**Baseline**
- End-to-end pipeline from one command: extract audio → speech recognition with word-level timestamps → sentence grouping → translation → text-to-speech (preset voice, no cloning) → timing → merge back into video
- Korean → English dubbed video that is watchable
- No progressive timing drift over a several-minute clip
- Output quality rated by English speakers

**Target**
- Error propagation measured per stage (ASR → translation → TTS/timing) on a small gold set
- Timing strategy when the translation is much longer or shorter than the source (0.8×–1.3× stretch, then re-translate shorter)
- Second language pair (TBD)
- Multiple speakers distinguished
- Cost per minute vs. professional and commercial AI dubbing, with an honest quality statement

**Stretch** — human watchability evaluation. Voice preservation and lip sync are out of scope.

## Team

| Member | Major | Role |
|---|---|---|
| Kalandarov Ulugbek | IBT | Team Representative / PM |
| Isokulov Azamat | IBT | Problem & Business |
| Samandarov Madina | IBT | Data & Research, User & Requirements |
| Musurmonov Jakhongir | IBT | Demo & Presentation |
| Tagaev Rashid | ISE | AI / Technical Lead |
| Kholmirzaev Temurjon | ISE | Software / IT Engineer |

Details in [docs/team.md](docs/team.md).

## Tech stack (planned, all free / open source)

ffmpeg · WhisperX · NLLB-200 (distilled-600M) · Kokoro-82M TTS · Python 3.10+

Starter template: [humblebeeai/module-python-template](https://github.com/humblebeeai/module-python-template) — chosen because DUBBE is a batch command-line pipeline and needs no HTTP API or database.

## Data

No video or audio files are stored in this repository. Full plan and licence rules in [docs/data-sources.md](docs/data-sources.md). Each test clip will be listed here with its source URL, licence, collection date, personal-data check, and preprocessing.

| Clip | Source | Licence | Date | Personal data | Preprocessing |
|---|---|---|---|---|---|
| TBD | KOCW / K-MOOC / team-recorded (with consent) | Per clip; No-Derivatives licences rejected | | | |

## Setup and run

TBD — will be added once the pipeline runs from a clean clone (Week 3 target).

## Credits

Problem statement and Definition of Done are from the HBAI Capstone Project Pool, tab C2b. Third-party models and their licences are listed in [docs/project-overview.md](docs/project-overview.md#8-tools-models-free-path-hardware). AI tools (Claude) were used to help draft and revise documentation; all content was reviewed by the team.
