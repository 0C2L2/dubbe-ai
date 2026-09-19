# Team 1 — Roles and Responsibilities (draft, 2026-09-20)

Inha University · IBT / ISE · Fall 2026 · HumbleBeeAI Capstone · Project C2b (DUBBE)

## Required role owners

Every course role has an owner (one person may hold several).

| Course role | Owner | Backup |
|---|---|---|
| PM — schedule, task assignment, submissions | Kalandarov Ulugbek | Musurmonov Jakhongir |
| Problem & Business — problem, user, value proposition, feedback | Isokulov Azamat | Samandarov Madina |
| Data & Research — data sources & licences, evaluation criteria, rating study | Samandarov Madina | Tagaev Rashid |
| AI / Engineering — pipeline, models, runtime | Tagaev Rashid | Kholmirzaev Temurjon |
| Demo & Presentation — demo video, slides, README | Musurmonov Jakhongir | Kholmirzaev Temurjon |

## Members

| Member | ID | Major | Role(s) | Responsibilities during development | Work to finish by next submission | Reviewer | Links |
|---|---|---|---|---|---|---|---|
| Kalandarov Ulugbek | 12235596 | IBT | Team Representative / PM | Team coordination, schedule, task assignment, instructor communication, progress tracking, submissions | Post repo link in Telegram; set weekly meeting; task board with owner / done-when / date | Jakhongir | TBD |
| Isokulov Azamat | 12230290 | IBT | Problem & Business | Target-customer research, market/problem analysis, competitor research, value proposition, business case, cost comparison | Competitor + pricing table (ElevenLabs, HeyGen, Rask, YouTube auto-dub, human dubbing) for the Target cost-comparison item | Madina | TBD |
| Samandarov Madina | 12235539 | IBT | Data & Research; User & Requirements Research | Target-user analysis, user requirements, use cases, pain points; data sources & licences; evaluation rubric; English rating panel | Select 2–3 openly licensed Korean lecture clips and record licence/URL; draft the rating rubric | Azamat | TBD |
| Musurmonov Jakhongir | 12230337 | IBT | Demo & Presentation | Presentation materials, demo narrative, project documentation, business communication, final report | Ground rules doc; keep README/docs current; start slide outline | Ulugbek | TBD |
| Tagaev Rashid | 12235611 | ISE | AI / Technical Lead | System architecture, AI pipeline, model selection, ASR, translation, pipeline integration, technical testing and evaluation | Environment spike: WhisperX + NLLB on one 2-min clip in Colab; C1/C2 diagram draft | Temurjon | TBD |
| Kholmirzaev Temurjon | 12235652 | ISE | Software / IT Engineer | Python implementation, audio/video processing (ffmpeg), TTS, timing synchronization, software integration, testing, debugging, repository infrastructure | Scaffold repo from module-python-template; `.gitignore` + `.env.example`; TTS + ffmpeg timing spike | Rashid | TBD |

## Cross-assignments (so planning ≠ IBT and code ≠ ISE)

- IBT members create the gold transcript/translation for the error-propagation study and act as English raters.
- ISE members write the *Why AI* and *Inputs / Outputs* sections of the overview and present them at review.
- Everyone can explain who DUBBE is for and how each pipeline stage works.

## Working agreement (summary — full version in ground-rules.md, TBD)

- Weekly meeting: **TBD day/time**; absence announced in advance.
- Each task has an owner, a "done when", a target date, and a reviewer.
- Code changes go through a pull request reviewed by the named reviewer before merge.
- No API keys, video, or audio files in the repository.
