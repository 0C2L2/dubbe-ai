# DUBBE — Competitor Analysis (draft, checked 2026-10-14)

Who else turns a video into a dubbed video, what they offer, what they cost, and where DUBBE is different — or not.

**How to read this.** Facts marked *official* come from the vendor's own docs or pricing page. Everything else comes from review sites and competitor blogs, which often **conflict** and have commercial interests (several are written by rival vendors). Prices change often: re-check before using any number in the final report. "—" means we found no evidence either way, not that the feature is missing.

## 1. Feature comparison

| | ElevenLabs | HeyGen | Rask AI | YouTube auto-dub | Perso AI (ESTsoft, Korea) | pyVideoTrans (open source) | **DUBBE** |
|---|---|---|---|---|---|---|---|
| Languages | **94** + dialects, Korean ✅ *(official)* | 175+ | 130+ | 27, Korean ✅ (directions vary) | 33–99+ (sources differ), Korean ✅ | many (depends on chosen models) | 2 tested (ko↔en); designed for any |
| Voice | Clone of the speaker ("cloning strength" 0–10) or voice library *(official)* | Clone | Clone in 32 languages | Synthetic; "Expressive Speech" in 8 languages (not Korean in the official 8) | Clone in 33 languages | Clone or preset (several engines) | **Preset voices only** (course rule: no cloning); matched to speaker's pitch register |
| Lip sync | ❌ "does not offer lip syncing" *(official)* | ✅ (more credits) | ✅ higher tiers only | Pilot: select creators, 5 languages | ✅ paid plans | — | ❌ (out of scope) |
| Multiple speakers | ✅ up to 32 *(official)* | — | ✅ auto-detect | — | ✅ up to 10 | ✅ (diarization) | ⬜ planned (C7) |
| Background music/effects kept | ✅ *(official)* | — | — | — | — | — | ✅ (Demucs; tested: phone ring −0.0 dB) |
| Edit transcript / translation | ✅ Dubbing Studio (now maintenance mode); v2 in UI; via API Enterprise-only *(official)* | ✅ Edit & Review + brand glossary | ✅ transcript editor | — | ✅ script editor | subtitles editable (details unclear) | ✅ edit `segments.json`, rerun from TTS |
| Regenerate one segment | ✅ *(official)* | — | — | — | — | — | ✅ (`--from tts`) |
| **Per-sentence "check this" flags** | ❌ none found | ❌ none found (proofreading, no flags) | ❌ none found | ❌ none found | ❌ none found | ❌ none found | ✅ ASR / translation / timing flags + review list |
| Timing fit | dynamic vs fixed clip length *(official)* | — | — | — | — | speed-up | speed-up ≤ 1.3×, shorter wording, optional picture slow-down |
| Runs locally (data stays on device) | ❌ cloud | ❌ cloud | ❌ cloud | ❌ YouTube only | ❌ cloud | ✅ offline possible | ✅ fully local |
| API | ✅ *(official)* | ✅ | ✅ | ❌ | — | CLI | CLI + local web page |
| Free tier | Free plan exists; Dubbing Studio from Starter *(official)* | small free tier (limits conflict) | 3-min trial only | **free** for YouTube creators | free tier with watermark | free (GPL-3.0) | free |
| Status / limits | Dubbing v2 "in alpha"; output "a high-quality preview, not a production master"; ≤ 1 GB / 180 min *(official)* | lip sync weaker on some languages, side angles | lip-sync uses 2–3× credits | auto-dub only for videos on YouTube | — | ~19k GitHub stars, v4.15 | prototype, tested on 3 clips |

## 2. Price per dubbed minute

| Tool | Plan prices | Effective $/minute | Source quality |
|---|---|---|---|
| ElevenLabs | Starter $6 · Creator $22 · Pro $99 · Scale $299 · Business $990 per month; dubbing costs 2,000–3,000 credits/min (automatic) or 5,000–10,000 (Dubbing Studio) | **≈ $0.50–0.60** automatic, no watermark · **≈ $1.65–2.00** Dubbing Studio, no watermark (our calculation from official credits) | *official* credits; project tab quotes $0.33–2.20 |
| HeyGen | Creator ~$29/mo (600 credits); lip-sync translation 5 credits/min, audio-only 2 credits/min | ≈ $0.10–0.25 by credits (but Pro price reported as $49 *or* $99; audio-only reported as free on some plans) | review sites, conflicting |
| Rask AI | Creator $50–60/mo for ~25 min; Creator Pro $120–150; overage $3/min | ≈ $2–3 | review sites, conflicting |
| Perso AI | Starter $6.99 · Creator $29 · Pro $99 /mo | vendor says $1.00 / $0.73 / $0.55 | vendor's own blog |
| CAMB.AI | free ~15 min/mo, Essentials $5, Pro $20 (one source) | — | one source |
| Dubverse | ~$15–20/mo, ~4 credits/min | — | review sites |
| Deepdub | enterprise only, custom quote | — | — |
| YouTube auto-dub | free | $0 (YouTube-hosted videos only) | official blog |
| Human studio dubbing | $5,000–15,000 per hour per language (vendor-adjacent figure) | ≈ $80–250 | unverified |
| **DUBBE** | local GPU | **electricity ≤ $0.0001/min; ≈ $0.0025/min on a rented cloud GPU** (measured run time, price assumptions in `languages.yaml`) | our measurement |

## 3. Short profiles

**ElevenLabs** — the strongest voice quality and the best documented. Automatic Dubbing v2 (alpha) does translation and voice in one pass, clones each speaker with an adjustable strength, keeps the background audio, handles up to 32 speakers and 94 languages including Korean. The detailed editor (Dubbing Studio: edit transcript/translation, drag clip timing, split/merge, regenerate clips, export SRT/AAF/CSV) is now in maintenance mode. No lip sync. No quality or confidence indicators in the docs.

**HeyGen** — video-avatar company; video translation with **lip sync** is its headline. 175+ languages, voice cloning, an Edit & Review step to correct the translated script and a brand glossary to lock names and terms. Credit-based pricing; reviewers report weaker lip sync for some languages and camera angles.

**Rask AI** — 130+ languages, voice cloning in 32, automatic multi-speaker detection, transcript editor before dubbing, lip sync on higher tiers. The most expensive per minute among self-serve tools; no permanent free tier.

**YouTube auto-dubbing** — free, built into YouTube for all eligible creators since 2026, 27 languages (Korean included in some directions), "Expressive Speech" keeps tone in 8 languages, lip sync only as a pilot. Over 6 million daily viewers watched dubbed content (Dec 2025). Only works for videos published on YouTube; no file you can take elsewhere (LMS, course platforms, internal training).

**Perso AI** — by ESTsoft, a Korean company: the most relevant *local* competitor. Cheap entry plan ($6.99), lip sync on paid plans, voice cloning in 33 languages, up to 10 speakers, script editor.

**CAMB.AI / Deepdub / Dubverse / Vozo** — CAMB.AI: own models, 150+ languages, broadcast focus. Deepdub: enterprise film/TV, emotion preservation, quote-only. Dubverse: strong on South Asian languages. Vozo: lip sync on premium tiers.

**pyVideoTrans** (open source, GPL-3.0) — the closest to DUBBE technically: a full local pipeline (Whisper → translation → TTS → merge) with GUI and CLI, many interchangeable engines, speaker diarization, can run fully offline. No review list or quality flags found.

**Text-translation quality tools (Smartling, Lokalise)** — not dubbing tools, but they already score each translated segment without a reference and send low scores to human review. This is **prior art for DUBBE's flags**: the idea is not new for text; we found it in no self-serve dubbing tool. One enterprise dubbing vendor (Truefan) markets blended dubbing QA scores.

## 4. Where DUBBE stands — honestly

**Different:**
1. **A review list instead of a black box.** Every competitor returns a finished video; none of the self-serve dubbing tools we checked tells the user *which sentences to check and which stage failed*. DUBBE flags low ASR confidence, low translation confidence and timing overflow per sentence, and the project measures how errors propagate. This matches the project tab's core lesson. Claim it narrowly: per-segment quality estimation exists for text translation, and our flags still miss confident errors (see [test-results.md](test-results.md)).
2. **Fully local, $0 per minute.** No uploads to a cloud service, no per-minute fees — relevant for unpublished lectures, internal training and privacy-sensitive content. Only open-source tools (pyVideoTrans) share this.
3. **Transparent and editable** — every stage writes a readable file; any sentence can be corrected and re-synthesized.
4. **Picture slow-down for long translations** — we found no competitor advertising this (not verified as absent).

**Behind:**
- Voice quality: commercial voices (and their cloning) sound far more natural; our Korean voice (MMS) sounds flat.
- No lip sync (HeyGen, Rask, Perso have it); no multiple speakers yet (all major tools have it).
- 2 languages tested vs 27–175.
- No polished editor UI; prototype tested on three clips.
- Voice cloning is ruled out by the course, which competitors use as a selling point.

## 5. What this means for the business case

- **Price alone is not a strategy.** AI dubbing already costs ~$0.10–3 per minute, and YouTube does it for free. DUBBE's cost (≈ $0.003/min on a rented GPU) is lower still, but the buyer's real cost is *checking* the output.
- **Pitch: "a dub you can trust, with a short list of what to check."** Saved reviewer time per minute of video is the measurable value — this is what the error-propagation study (T-05/T-07) should prove.
- **Target content YouTube cannot reach:** courses on LMS and university platforms, paid course sites, internal training — private files that also should not leave the organisation.
- **Watch Perso AI** (Korean, cheap, lip sync) as the local benchmark, and **ElevenLabs** as the quality benchmark in the cost comparison (T-11).

## 6. Open questions

- Do any competitors expose confidence or quality scores in their APIs that we missed? (Check ElevenLabs/HeyGen API references.)
- YouTube auto-dub: does Korean → English work for lecture content, and how good is it? A side-by-side on the same clip would make a strong demo slide.
- Verify current prices on each vendor's pricing page right before the final report.

## 7. ElevenLabs website structure (checked 2026-10-15)

From their `sitemap.xml`, homepage HTML (header and footer) and the pages named below. The site is in **13 languages, Korean included**. The English sitemap has **≈ 5,500 URLs**, but most are generated search-engine pages; the real structure is ~225 pages.

**Header:** three product tabs — ElevenCreative · ElevenAgents · ElevenAPI (dropdown: AI Voice Generator, Text to Speech, Music, Speech to Text, Voice Cloning, Dubbing) · buttons **Log in · Sign up · Contact sales** · announcement bar ("Introducing Eleven v4").

**Homepage, in order:** hero "Bringing technology to life" + Sign up / Contact sales → use-case cards → customer logos → two platforms (Creative, Agents) → interactive text-to-speech demo (pick a voice, press play) → feature blocks → API section with code samples → showcase news → research timeline (Dubbing v2: May 2026; Eleven v4: Sep 2026) → "Safety, built in" (Moderation · Accountability · Provenance) → latest blog posts → closing CTA.

**Footer columns:** *Creative* (13 product pages) · *Agents* (11 industry pages) · *API* (10 links) · *Resources*: Blog, Iconic Marketplace, Impact Program, Startup Grants, Help Center, Webinars, Docs, Enterprise, Trust Center, India · *Socials* (12) · *Company*: About, Careers, Safety, Brand & Press Kit, Summit, Terms, Privacy, EU DSA, Modern Slavery, CCPA, EU-US DPF, AI Transparency, Human Rights.

| Page group | Examples | Count (EN) |
|---|---|---|
| Product pages | /text-to-speech, /speech-to-text, /dubbing-studio, /translate-video, /voice-cloning, /voice-isolator, /music, /studio, /video, /image | ~40 |
| AI agents (industries, templates) | /agents/healthcare, /agents/financial-services … | 54 + 77 + 27 + 36 |
| Pricing | /pricing (Creative), /pricing/agents, /pricing/api | 3 |
| Account | /app/sign-up, /app/sign-in (sign-in methods not checked: the page is rendered by JavaScript) | 2 |
| Contact | /contact-sales, /contact-partnerships, /contact-legal (no general contact page; support goes through the Help Center) | 3 |
| Audience pages | /students, /creators, /teams, /enterprise, /government, /startup-grants, /impact | ~10 |
| Trust and safety | /safety, /ai-speech-classifier, /use-policy, /ai-transparency + compliance.elevenlabs.io | 4 + 1 |
| Legal | terms (≈ 25 product-specific terms pages), privacy, DPA, DSA, CCPA, … | ~35 |
| Company | /about, /careers (148 job pages), /brand, /press, /customer-stories, /events, /webinars (82) | ~240 |
| Content | /blog (710 articles, 181 author pages), /insights (5) | ~900 |
| Generated search pages | sound-effect categories 2,440 · voice-library collections 580 · music categories 305 · audio/video-to-text 100 · voice changer 103 · translate-video **55** (e.g. /translate-video/korean-to-english) · translate-audio 55 · languages 109 (e.g. /text-to-speech/korean) | ~3,800 |
| Help Center (help.elevenlabs.io) | categories: Technical, Account, Product, Troubleshooting, Legal, Website, Other; sections incl. Dubbing, Payment & Billing, Cancelation & Refunds, Legal & Safety | 7 categories, ~33 sections |

**Pages that matter for DUBBE:**
- **/pricing:** Free $0 (10k credits), Starter $6, Creator $22, Pro $99, Scale $299, Business $990, Enterprise custom; annual = 10 × monthly. **Dubbing Studio (the editor) not on Free.** Credits per dubbed minute: automatic 2,000 with watermark / 3,000 without; Studio 5,000 / 10,000. 11 FAQ questions (credits, reset and rollover, upgrade/downgrade/cancel, remaining credits, payment methods).
- **/dubbing-studio:** "Localize content across 90+ languages with AI dubbing"; CTAs "Start dubbing free" / "Talk to sales"; claims: keeps the original emotion and timing, clones the speaker automatically, "Close to Human-Quality"; two paths — self-serve, or *Productions* (human translators, casting, mixing); 4 FAQ questions; a static UI picture, no demo video; **no quality or confidence information**.
- **/translate-video/korean-to-english** (same template for 55 pairs): 5 steps (upload → pick languages → "Machine generated" or "Human edited" → review timing → export), 5 reasons, 5 use cases with **"Education and training" first**, 7 FAQ questions.
- **/safety:** Prevent (red-teaming, customer vetting, blocks cloning of celebrity and high-risk voices, verification for professional clones) · Detect (classifiers + human review) · Enforce (bans) · Inform (C2PA, public AI audio classifier) · report-content form.
- **/ai-speech-classifier:** free, no login; upload audio/video, first minute analysed, probability that **ElevenLabs** made it; does not reliably detect their Eleven v3 model; no accuracy figures given.
- **/students:** "expanded access to free plans" for students and professors at verified institutions (school email); no numbers on the page.

## Sources

Official: [ElevenLabs Dubbing docs](https://elevenlabs.io/docs/overview/capabilities/dubbing) · [ElevenLabs Dubbing Studio](https://elevenlabs.io/docs/eleven-creative/products/dubbing/dubbing-studio) · [ElevenLabs pricing](https://elevenlabs.io/pricing) · [YouTube blog: auto dubbing](https://blog.youtube/news-and-events/youtube-auto-dubbing-expressive-speech/) · [YouTube Help: automatic dubbing](https://support.google.com/youtube/answer/15569972?hl=en) · [pyVideoTrans on GitHub](https://github.com/jianchang512/pyvideotrans)

Reviews and news (vendor-adjacent, often conflicting): [HeyGen video translation guide](https://fluxnote.io/guides/heygen-video-translation-guide) · [HeyGen pricing](https://checkthat.ai/brands/heygen/pricing) · [HeyGen review (by Perso)](https://perso.ai/blog/heygen-ai-dubbing-review-2026) · [Rask AI pricing](https://blog.geckodub.com/rask-ai-pricing-plans-alternatives) · [Rask AI review (by Perso)](https://perso.ai/blog/rask-ai-dubbing-review-2026-features-pricing-how-it-compares) · [Perso on Capterra](https://www.capterra.com/p/10041483/Perso-AI/) · [Perso on G2](https://www.g2.com/products/perso-dubbing/reviews) · [Perso: AI dubbing pricing](https://perso.ai/blog/ai-dubbing-pricing-2026-cost-per-minute-compared) · [Slator: YouTube expressive speech](https://slator.com/youtube-multilingual-expressive-speech-ai-dubbing/) · [PPC Land: YouTube 27 languages](https://ppc.land/youtube-auto-dubbing-tops-6m-daily-viewers-expands-to-27-languages/) · [Dupple: best AI dubbing tools](https://dupple.com/learn/best-ai-dubbing-tools) · [Vozo: AI vs studio dubbing cost](https://www.vozo.ai/blogs/ai-dubbing/ai-dubbing-vs-traditional-cost) · [Open-source dubbing tools 2026](https://videodubbing.com/blog/post/best-open-source-video-dubbing-tools-2026/)

Quality estimation (prior art for review flags): [Smartling: AI quality estimation](https://www.smartling.com/blog/ai-quality-estimation) · [Lokalise: AI scoring](https://lokalise.com/product/ai-scoring/) · [Translated: quality scoring](https://translated.com/resources/ai-powered-translation-quality-scoring-trust) · [Truefan: dubbing quality scoring](https://www.truefan.ai/blogs/video-dubbing-accuracy-metrics)
