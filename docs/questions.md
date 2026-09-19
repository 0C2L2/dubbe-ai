# Question Log

Format from the course documentation guide. Status: Not checked / Under review / Decided.

| ID | Question | Related DoD item | Why it matters | Tried | Who to ask | Status | Decision / date | Follow-up |
|---|---|---|---|---|---|---|---|---|
| Q-001 | We chose **online course creators** as the buyer (tab offers company / education provider / creator). Is it fine that the *test data* is university lectures while the *buyer* is creators? | Problem definition | Overview and business case depend on it | Discussed both options in team drafts | Instructor | Not checked | | Azamat |
| Q-002 | KOCW content is CC BY-NC-SA. May we use it as test input, and may we publish a short dubbed demo clip under the same licence with attribution? | Baseline: watchable dubbed video; Data path | Determines which clips we can show at Demo Day | Read KOCW licence page | Instructor / mentor | Not checked | | Madina |
| Q-003 | May we send transcript text or audio to an external AI service (e.g. a free-tier LLM API) for translation, or must everything run locally / on Colab? | Baseline: translation; Target: length-aware timing | Changes translation model choice and the cost table | Nothing yet — Baseline plan uses local NLLB | Instructor | Not checked | | Rashid |
| Q-004 | Is Google Colab free tier enough for WhisperX large-v3-turbo + NLLB-600M on a 5–10 min clip? Is any lab GPU available? | Baseline: full pipeline | Tab requires confirming the free path in Weeks 2–3 | Nothing yet | Mentor / team spike | Not checked | | Rashid, Temurjon |
| Q-005 | Which second language pair? Must be one a teammate can evaluate. | Target: second language pair | TTS availability differs a lot by language | Nothing yet | Team | Not checked | | Ulugbek |
| Q-006 | What is the minimum acceptable human-review step? Is "edit `segments.json` → re-synthesize that segment" enough, or is a UI expected? | Scope rule: AI output must be editable and human-approved | Decides whether we build any UI at all | Nothing yet | Instructor | Not checked | | Temurjon |
| Q-007 | Who rates English output quality? Team members only, or can we recruit international students at Inha (consent process)? | Baseline: quality assessed by target-language speaker; Stretch: human evaluation | Evaluation credibility | Nothing yet | Instructor | Not checked | | Madina |
| Q-008 | Kokoro-82M (Apache, CPU) vs. Coqui XTTS-v2 (suggested in tab, needs GPU, non-commercial licence) for preset-voice TTS? | Baseline: synthesize | Runtime and licence | Desk research only | Team spike | Under review | | Temurjon |
