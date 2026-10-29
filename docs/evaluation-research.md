# DUBBE — Evaluation Research: human ratings, "teacher" references, error propagation (checked 2026-10-14)

What published research and vendor documentation say about the team's proposed evaluation design:
(1) users rate parts of the video on the timeline; (2) a strong commercial system (e.g. ElevenLabs) is used as a "teacher" to compare our output against; (3) bigger or fine-tuned models.
Sources at the end. Vendor numbers are marked as such.

## 1. Rating parts of the video — what the research supports

**The standard method already works this way.** Since 2024, the WMT human evaluation uses **Error Span Annotation (ESA)**: the rater marks the wrong spans first, then gives the segment a 0–100 score. Against expert MQM rankings it reached 94.9 % pairwise ranking accuracy and Spearman ρ = 0.973, and it is faster and cheaper than MQM and needs no MQM-trained experts (Kocmi et al., 2024; validated on English→German only). DUBBE's timeline rating can copy this: select a sentence block → mark what is wrong (wrong meaning / wrong word / missing / mispronounced / cut off / timing) → score 0–100.

**Three problems the research points to:**
1. **Seeing the flags biases the raters.** Showing quality-estimation highlights changes what people check and can cause over-reliance on the model's predictions (Zouhar et al., 2021, as summarised by QE4PE; QE4PE also found highlights changed editing behaviour differently per language pair). If raters see DUBBE's flags, their ratings cannot be used to test whether the flags are right (T-07). → An evaluation mode with flags hidden, rating a random sample of all sentences.
2. **One rater is not enough.** Agreement between raters is low even with trained annotators (ESA Kendall's τc = 0.149, MQM 0.109). → At least 2 raters per sentence for the numbers we report.
3. **The rater must understand the target language** (project tab, Baseline). A Korean creator dubbing into English may not judge English adequacy well. In-product ratings help collect data; they do not replace recruiting target-language raters (Q-007).

## 2. A commercial system as the "teacher"

**What we can get from ElevenLabs (official API docs):** the dub, the **source transcript** (its ASR) and the **target transcript with source text and translation per segment** (project transcript endpoints; legacy endpoints return SRT/WebVTT). So we get teacher outputs **per stage**, which is what an error-propagation study needs.

**Using it for training is not allowed.** ElevenLabs' Prohibited Use Policy forbids using the services or output "to develop, train, fine-tune, or improve any AI model … or including Output in a dataset" for those purposes (exceptions not visible in the excerpt; check the full text). So ElevenLabs can be a teacher for **evaluation only**, not for distillation into our models. The same restriction exists in most commercial AI terms; a teacher used to *train* must be an open-weight model whose licence allows it.

**A teacher is not ground truth.** Machine output used as a reference ("pseudo-reference") inherits that system's errors (pseudo-reference literature since Albrecht & Hwa, 2007), and reference-based metrics shift with the reference used (Freitag et al., 2020). A score of "agreement with ElevenLabs" measures similarity to ElevenLabs, not correctness — if both make the same mistake, it looks perfect. Vendor numbers on ElevenLabs' Korean ASR: Scribe v1 10.7 % WER vs Whisper large-v3 18.1 % on FLEURS (ElevenLabs' own page, not independent). Our measured Whisper large-v3-turbo CER on 12 FLEURS Korean sentences is 9.9 % — CER and WER are not comparable, so the teacher's advantage on our data is unknown until measured.

**How to use a teacher correctly:**
1. **Validate the teacher first** on a small human-checked set (e.g. 50 sentences): how often is the teacher itself wrong?
2. **Report agreement, not accuracy**, unless the teacher was validated.
3. **Triangulate** with reference-free metrics, which need no teacher: in the WMT24 metrics task, average correlation with human judgement was MetricX-24-Hybrid 0.721, XCOMET 0.719, reference-free MetricX-24-QE 0.714, an LLM-judge (GEMBA-ESA) 0.711, CometKiwi 0.640.
4. **LLM as judge** (GEMBA: GPT-4 prompted like a human rater) reaches state-of-the-art accuracy at system level; the authors warn that a proprietary black-box judge is risky for research claims. LLM judges show position bias and self-preference (Judging the Judges, IJCNLP 2025; Beyond the Surface, EMNLP 2025). → Fixed prompt, randomised order, a judge model different from the translator.

## 3. Error propagation with a teacher — the design that isolates each stage

Replace one stage's output with the teacher's version and see how much the end result changes ("oracle substitution", the standard way to separate ASR and MT errors in cascaded speech translation):

| Run | ASR | Translation | Measures |
|---|---|---|---|
| A — ours | ours | ours | the real output |
| B — teacher ASR | teacher's transcript | ours | A vs B = damage caused by our ASR |
| C — teacher translation | teacher's transcript | teacher's translation | B vs C = damage caused by our translation |
| D — synthesis | — | — | our TTS re-transcribed by Whisper vs the text it was asked to say = TTS errors |

Quality of each run is measured with the human ratings where available, otherwise the triangulated metrics above. The "teacher" is validated on the human subset before its numbers are trusted.

## 4. Bigger models and fine-tuning

- **Strongest translation systems (WMT25 human evaluation):** Gemini 2.5 Pro was in the top cluster for 14 of 15 language pairs (closed model); Shy-hunyuan-MT was the best constrained system (11 pairs). **Hunyuan's licence excludes South Korea** (checked earlier in this project) — not usable here. Open models in the results: Qwen3-235B (too large for one cheap GPU), Gemma-3-27B (fits one 80 GB GPU in 16-bit). WMT25 has **no Korean–English human results**, so the best model for our pair must be measured on our gold set.
- **Cost on cloud GPUs:** an 80 GB A100 is listed at $0.90/h on Nosana (their page) — affordable for evaluation runs.
- **Fine-tuning needs data we do not have:** in-domain Korean–English lecture sentence pairs. Teacher outputs from commercial services cannot be used (terms above). Options: AI Hub parallel corpora (Korean identity registration, training-only clauses — likely inaccessible, see data-sources.md), team-made gold data (too small to train on), or distillation from an open-weight teacher whose licence allows it.

## Sources

- Kocmi et al., *Error Span Annotation*, WMT 2024 — [ACL Anthology](https://aclanthology.org/2024.wmt-1.131/) · [code](https://github.com/wmt-conference/errorspanannotation)
- Kocmi & Federmann, *Large Language Models Are State-of-the-Art Evaluators of Translation Quality*, EAMT 2023 — [ACL Anthology](https://aclanthology.org/2023.eamt-1.19/) · *GEMBA-MQM*, WMT 2023 — [ACL Anthology](https://aclanthology.org/2023.wmt-1.64/)
- *Are LLMs Breaking MT Metrics? Results of the WMT24 Metrics Shared Task* — [PDF](https://repository.tilburguniversity.edu/server/api/core/bitstreams/b51a379b-dc19-44a7-bf79-1f4f56d37e52/content) · MetaMetrics-MT (WMT24 tables) — [arXiv](https://arxiv.org/pdf/2411.00390) · MetricX-24 — [arXiv](https://arxiv.org/pdf/2410.03983)
- Findings of WMT25 General MT — [ResearchGate](https://www.researchgate.net/publication/397421096_Findings_of_the_WMT25_General_Machine_Translation_Shared_Task_Time_to_Stop_Evaluating_on_Easy_Test_Sets) · preliminary ranking — [arXiv](https://arxiv.org/pdf/2508.14909)
- Pseudo-references and reference bias — [The Role of Pseudo References in MT Evaluation](https://aclanthology.org/W08-0330.pdf) · [In the Blind: Building Pseudo-References](https://arxiv.org/html/2609.13611) · [Trained MT Metrics Learn to Cope with Machine-translated References](https://arxiv.org/pdf/2312.00536)
- QE shown to post-editors — [QE4PE](https://arxiv.org/pdf/2503.03044) · [Zouhar et al. 2021, EMNLP](https://aclanthology.org/2021.emnlp-main.801/) · [Slator summary](https://slator.com/does-word-level-quality-estimation-really-improve-ai-translation-post-editing/)
- LLM-judge bias — [Judging the Judges (position bias), IJCNLP 2025](https://aclanthology.org/2025.ijcnlp-long.18.pdf) · [Beyond the Surface (self-preference), EMNLP 2025](https://aclanthology.org/2025.emnlp-main.86/)
- ElevenLabs API — [source transcript](https://elevenlabs.io/docs/api-reference/dubbing/source-transcript/get-source-transcript) · [target transcript](https://elevenlabs.io/docs/api-reference/dubbing/target-transcript/get-target-transcript) · [legacy SRT transcript](https://elevenlabs.io/docs/api-reference/legacy/dubbing/get-transcript-for-dub) · [Prohibited Use Policy](https://elevenlabs.io/use-policy) · [Korean speech-to-text page (vendor WER table)](https://elevenlabs.io/speech-to-text/korean)
