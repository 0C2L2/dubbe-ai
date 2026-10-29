# DUBBE — UzCombinator Season 3 application (draft)

> **For the team, not for the form.** Applications close **31 October 2026** (uzcombinator.uz). The form is behind a login,
> so its exact questions are unknown; the site says it takes ~10 minutes, needs no pitch deck, and asks you to describe what
> you are building in your own words. Next: a 30-minute interview **in person in Tashkent**, then a 45-day programme in
> Tashkent (Shayxontohur, Alisher Navoiy 11A) with a $1,000 stipend and a Demo Day. UzCombinator takes equity, agreed with
> each team at the interview. Copy the sections below into whatever the form asks.
>
> **Decide before submitting:**
> 1. **Who applies and who can be in Tashkent** for the interview and the 45 days.
> 2. **Who owns DUBBE:** it started as a course capstone (Inha University × HumbleBeeAI). Ask the instructor whether the
>    team may take it to an accelerator and give equity.
> 3. **Licences:** the translation model (NLLB-200, CC-BY-NC) is non-commercial. A paid product needs another model
>    (plan C20 lists candidates). Do not promise paid plans before that.
> 4. **Uzbek is not supported yet.** Whisper and NLLB list Uzbek, but we have not measured them, and there is no Uzbek
>    voice (plan C20). Say "next", not "done".
> 5. Fill in every **TBD**.

---

## One line

DUBBE dubs and subtitles videos between 22 languages with AI, and shows a person which sentences to check before anyone
watches.

## What we are building (in our own words)

People who make lectures, courses and training videos want them in other languages, but AI dubbing makes mistakes that
nobody sees until a viewer does: a misheard word becomes a wrong translation, then fluent speech saying something wrong.
Checking a dub by ear takes as long as the video, so most people either don't check or don't dub.

DUBBE is a website that dubs a video into another language — speech recognition, translation, a voice for each speaker,
background music kept, each sentence placed where it was said — and marks the sentences where it was unsure, so a reviewer
starts there instead of listening to everything. Corrections are kept and re-dubbed. The same pipeline makes subtitles
with a colour per speaker, transcripts, text to speech and speaker detection.

It runs today on our laptop GPU in 22 languages. Next: Uzbek, and the first real users.

### Uzbek version — a native speaker in the team must check it

DUBBE — videolarni 22 til o‘rtasida sun’iy intellekt yordamida dublyaj qiladigan va subtitr tayyorlaydigan veb-sayt.
U tekshirish kerak bo‘lgan gaplarni belgilab beradi: tekshiruvchi butun videoni tinglash o‘rniga shu gaplardan boshlaydi.
Nutqni taniydi, tarjima qiladi, har bir so‘zlovchiga alohida ovoz beradi, fon musiqasini saqlaydi va har bir gapni aytilgan
joyiga qo‘yadi. Hozir noutbukimizdagi GPU’da 22 tilda ishlaydi; keyingi qadam — o‘zbek tili va birinchi foydalanuvchilar.

## The problem

- AI dubbing costs ≈ $0.10–3 per dubbed minute (ElevenLabs, HeyGen, Rask, Perso; `docs/competitors.md`), and YouTube dubs
  its own videos for free. None of the tools we checked tells the user **which sentences may be wrong**.
- So the real cost is checking: a 60-minute lecture needs ~60 minutes of listening per language, by someone who knows both.

## The product today (measured — `docs/test-results.md`)

| What | Measured |
|---|---|
| Languages | 22, any pair. Korean ↔ English tested in depth; the other 20 on read speech only |
| Speech recognition, Korean (Whisper large-v3) | 5.3 % character errors on read speech (100 sentences), 11.7 % on conversation (150 clips) |
| Translation (NLLB-200 3.3B), 529 Korean–English sentence pairs | chrF++ 52.3 ko→en, 32.8 en→ko (49.3 / 29.4 with the model we replaced) |
| Several speakers | two-person dialogue: 13 of 13 sentences on the right speaker; each speaker gets their own voice |
| Voices | preset voices in all 22 languages; a speaker can keep their own voice, only with consent (similarity 0.85 vs 0.66 for a stock voice) |
| Timing | largest delay 0.00 s on three test clips (one needed the picture slowed down 1.2×) |
| Speed | 29 s of processing per video minute into English, 77 s into Korean, one laptop GPU (RTX 4060) |
| Cost | ≈ $0.003 per video minute into English, $0.007 into Korean, at an assumed $0.35/hour rented GPU |
| Review flags | first test, 15 sentences: 3 flagged, 2 of them wrong; about 8 were wrong, so ~6 were missed |
| Also | colour-coded subtitles (SRT, WebVTT, ASS, burned into the video), speech to text, text to speech, voice isolation, a voice marketplace (no payouts) |

**Limits:** no users yet; not deployed (runs on our laptop); no fluent listener has rated any target language; flags miss
confident mistakes; short spoken lines are sometimes mistranslated; recognition is weak in Swahili (26 %), Turkish (17 %),
Hindi (13 %) and Malay (10 %); no lip sync.

## Who it is for

B2C and B2B:

1. **Content creators (B2C):** bloggers reaching audiences in other languages — Uzbek ↔ Russian ↔ English and more.
   YouTube's free auto-dub competes here for videos on YouTube.
2. **Online course creators and universities (B2C / B2B):** course videos on their own platforms, which YouTube's free
   dubbing does not reach.
3. **TV and dubbing studios (B2B):** long films and series dubbed for local audiences. DUBBE makes the first draft (a voice
   per speaker, music kept); the studio's people check the flagged sentences. Studios will need what we do not have yet:
   lip sync, an Uzbek voice, voices rated by native listeners.

*(TBD: market numbers with sources.)* First users we can reach ourselves: professors and classmates at Inha University.

## Competition

- **ElevenLabs, HeyGen, Rask, Perso, YouTube auto-dub:** better voices, lip sync (some), more languages, real customers.
- **DUBBE's difference:** a short list of sentences to check instead of a black box; every step editable; can run on the
  customer's own machine, so unpublished lectures need not be uploaded; lower cost per minute (measured above).
- **Where we are behind:** voice naturalness, lip sync, users. *(TBD: how well competitors handle Uzbek.)*

## Business model (not tested)

- Proposed plans on the website: Free 15 min/month; Creator $9 for 120 min; Pro $29 for 600 min. During the beta everyone
  is on Free and paid plans are a waitlist.
- Processing costs under one cent per video minute (measured above), which leaves room for servers and support.
- Before charging: replace the non-commercial models.

## Traction

No users or revenue. What exists: a working pipeline with 77 automated tests, measured results for each stage, and a
website (accounts, plans, editor, tools, admin) running locally.

## Team

Six students at Inha University (majors IBT and ISE), working on DUBBE since September 2026 as a capstone project.

| Name | Major | Role |
|---|---|---|
| Kalandarov Ulugbek | IBT | Team lead / PM |
| Isokulov Azamat | IBT | Problem & business |
| Samandarova Madina | IBT | Data & research |
| Musurmonov Jakhongir | IBT | Demo & presentation |
| Tagaev Rashid | ISE | AI / technical lead |
| Kholmirzaev Temurjon | ISE | Software engineering |

*TBD: who applies as founders, who works full-time during the 45 days, LinkedIn / GitHub, phone, email.*

## The 45 days

1. **Uzbek:** measure recognition and translation on Uzbek speech; add an Uzbek voice (plan C20).
2. **Online:** deploy the website.
3. **10 users:** lecturers and creators dubbing their own videos; measure how much listening the flags save.
4. **Price:** will they pay, and how much per minute.

## What we want from UzCombinator

Mentors for finding the first paying customers (universities, course platforms) and pricing; introductions to Uzbek
educational content owners; the stipend for hosting and a rented GPU (plan C20).

## Links

- Code: https://github.com/0C2L2/dubbe-ai *(check it is public before sharing)*
- Demo video: *TBD (2–3 min: upload → flagged sentences → fix → coloured subtitles)*
