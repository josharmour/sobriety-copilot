# Sobriety Copilot — Feature Requests & Marketplace Analysis

> **Scope:** Competitive marketplace analysis of the recovery/sobriety app landscape, distilled into the **top 10 missing features** for Sobriety Copilot, ranked by impact × fit × feasibility.
>
> **Date:** 2026-08-01
> **Method:** Codebase feature audit + three parallel research passes across ~20 live competitors (tracker, community/meeting, and literature/clinical apps). Research sources are cited in the companion inventories at `/Users/joshu/repos/sobriety-app-feature-inventory.md` and `/Users/joshu/repos/recovery_apps_feature_inventory.md` (real App Store listings, official sites, archived sources; missing data marked "not found", never guessed).

---

## 1. Landscape findings (read this first)

A handful of market facts shape everything below:

- **Two famous competitors are dead.** **Sober Grid** (the "Burning Desire" panic-button app) shut down in 2023–25; **Tempest** (Hip Sobriety) is defunct/parked. Nobody has cleanly inherited the "sober-social + emergency-support" niche → **white space**.
- **The official AA app (Everything AA)** is free, 4.9★, ~66k ratings, with a full audio Big Book + 12&12. Sobriety Copilot's literature library has to *out-UX* it, not just match it.
- **Dominant monetization** is subscription ($3.99–$39.99/yr tiered) or free core + paid coaching/premium (Loosid SAM, Reframe Pro, I Am Sober Plus).
- **Only one app** (AA 12-Step Toolkit, $39.99/yr) ships a *guided* full 12-step workbook with 4th-step moral inventory — and Sobriety Copilot already has a nightly 4th-step inventory, which is rare.

## 2. What Sobriety Copilot already has (baseline — don't re-list these)

- Literature-grounded **RAG chat with relevance-scored citations** (genuinely uncommon — most competitors are trackers, not literature-GPTs)
- **Private Mode** (on-device Gemma; nearly zero competitors)
- Offline reader with highlighting + saved passages; daily readings; category filters
- Sobriety tracker: day count, **keytag milestones**, money-saved, **discreet/shoulder-surfing mode**, home-screen widget
- **Find-a-meeting map** (in-person/online) + home-group manager with reminders
- Voice input (ASR) + neural TTS output
- Nightly 4th-step inventory
- Crisis hotline routing (AA helpline + 988/SAMHSA)

**Net:** a stronger literature + privacy core than anything in the market. The gaps are on the **motivation / social / safety / clinical** axes.

---

## 3. Top 10 Missing Features (ranked)

> **Owner triage (2026-08-01):** FR1, FR4, FR5, FR9 **approved** for implementation. FR2, FR3, FR6, FR7, FR8, FR10 **rejected** (plans removed) — they all step outside the on-device, single-user, private core: server infrastructure / other humans / ongoing moderation duty (FR2, FR6, FR7), legal/policy exposure (FR3 medical claims, FR10 copyright), or 12-step identity conflict (FR8 moderation mode). FR3 additionally judged too thin to carry.
>
> **Implementation plans:** each approved feature has a dedicated plan under `docs/plans/` (same FR identifier — cross-linked here).

| ID | Feature | Status | Plan |
|----|---------|--------|------|
| **FR1** | Relapse tracking with a shame-free day-reset | ✅ Approved | [`docs/plans/FR1-relapse-tracker.md`](docs/plans/FR1-relapse-tracker.md) |
| **FR2** | In-the-moment craving tool + panic/SOS button | ❌ Rejected | — |
| **FR3** | Calories-saved + health-recovery timeline | ❌ Rejected | — |
| **FR4** | Mood/emotion check-in + daily journal | ✅ Approved | [`docs/plans/FR4-mood-journal.md`](docs/plans/FR4-mood-journal.md) |
| **FR5** | Streaks + daily check-in gamification | ✅ Approved | [`docs/plans/FR5-streaks.md`](docs/plans/FR5-streaks.md) |
| **FR6** | Anonymous peer-support community feed | ❌ Rejected | — |
| **FR7** | Sober companions / accountability partners | ❌ Rejected | — |
| **FR8** | Multi-substance + moderation mode | ❌ Rejected | — |
| **FR9** | Meditation / breathing / grounding library | ✅ Approved | [`docs/plans/FR9-meditation.md`](docs/plans/FR9-meditation.md) |
| **FR11** | Personal companion memory (remembers you across conversations) | ✅ Approved | [`docs/plans/FR11-personal-memory.md`](docs/plans/FR11-personal-memory.md) |
| **FR10** | Audio Big Book + read-along | ❌ Rejected | — |

### <a id="fr1"></a> FR1. Relapse tracking with a shame-free day-reset
**Why #1:** Every major tracker (I Am Sober, Sober Time, Reframe, Recovery Path) supports logging a relapse, resetting the day counter *without punishing the user*, and keeping history/stats intact. Sobriety Copilot has a **monotonic** counter with no supported relapse flow. A user who slips has nowhere to go (start from zero or abandon the app). This is simultaneously a retention killer and a clinical-safety gap — and it's the moment the user needs the app *most*. It's the most universal competitor feature, and the hardest to be without.

### <a id="fr2"></a> 2. ❌ REJECTED — In-the-moment craving tool + "panic/SOS" button (Beacon / Burning-Desire style)
> *Rejected 2026-08-01: SMS/call side-effects to real contacts + optional server sink + app-store crisis-policy exposure. The grounding half is covered by FR9's "Surf the Urge" session.*
The most emotionally-loaded gap, sharpened by Sober Grid's death. Competitors route an urgent event to a human network: Sober Grid's **Burning Desire** (dead — position to inherit it), Recovery Path's **Beacon SOS** (SMS/WhatsApp to sponsor+family), Nomo's tempted-alert. SC's only crisis path is a **static hotline**. A craving-surfing tool (urge log + grounding/distraction) plus an **SOS that one-tap messages chosen support contacts** would differentiate — and can run **fully on-device in Private Mode**, doubling down on the privacy moat.

### <a id="fr3"></a> 3. ❌ REJECTED — Calories-saved + health-recovery timeline
> *Rejected 2026-08-01: too thin (a multiplication), and the health timeline carries medical-claim policy risk for marginal recovery value.*
SC tracks money saved but not **calories saved** or **time-boxed health benchmarks** (blood pressure, sleep quality, energy, skin at day 30/60/90) that I Am Sober, EasyQuit, and Try Dry use to sustain long-term motivation. Cheap to add (pure calculation + content), high daily-engagement value.

### <a id="fr4"></a> 4. Mood/emotion check-in + daily journal
SoberTool's signature feature is an **emotion selector** ("I'm feeling… Afraid / Grateful / Resentful…") that returns tips, plus journaling. SC's nightly 4th-step inventory is structured review, but there's **no free daily mood log or journal with a trend view**. The gap between "supervised check-in" and "the user's own reflective space."

### <a id="fr5"></a> 5. Streaks + daily check-in gamification
SC has milestones (keytags — great, competitors don't have the familiar chip colors), but no **streak / daily check-in loop** (I Am Sober's motivational threads, Try Dry's missions + badges). The daily-return hook keeps competitors sticky. **Milestones are the reward; a streak feed is the engine.**

### <a id="fr6"></a> 6. ❌ REJECTED — Anonymous peer-support community feed
> *Rejected 2026-08-01: server-hosted UGC from a vulnerable population = permanent human-moderation duty, crisis-response SLA, and the largest liability surface the app could add.*
Sober Sidekick (4.8★, ~7.9k ratings), Loosid, and I Am Sober all center on an anonymous sober social feed. Big gap — **but directly tensions with SC's privacy stance.** Middle path: a **self-hosted, anonymous, opt-in** feed on SC's own stack (you already run the server), with moderation handled in-house, unlike Big-tech-run competitors. With Sober Grid dead, there's white space. Medium-high value.

### <a id="fr7"></a> 7. ❌ REJECTED — Sober companions / accountability partners + sponsor connection
> *Rejected 2026-08-01: requires a server rendezvous relay + other humans; FR6-lite in liability terms. A local-only sponsor quick-contact could ride along with FR9 later at near-zero cost.*
Nomo's **1:1 sober partners** (its signature), Recovery Path's care team, I Am Sober's friend-and-groups. SC's **home-group manager** handles meeting reminders but there's **no 1:1 accountability partner or sponsor link.** Privacy-friendly version: pair two day-counts, send gentle "still sober together" nudges — stay on-device / share only what the partner opts into.

### <a id="fr8"></a> 8. ❌ REJECTED — Multi-substance tracking + harm-reduction/moderation mode
> *Rejected 2026-08-01: a moderation/drink-less track conflicts with the 12-step abstinence identity and the entire literature corpus — a half-product for a different audience.*
SC is strictly **AA-style alcohol abstinence.** Competitors track alcohol *and* drugs separately (I Am Sober, Sober Time, WEconnect), and a whole segment (Reframe, Sunnyside, Less, Try Dry, This Naked Mind) serves **moderation / drink-less** goals — not just abstinence. Adding (a) a nicotine/other-substance counter or (b) a moderation-track mode opens the audience well beyond the strict 12-step core without diluting the literature core.

### <a id="fr9"></a> 9. Meditation / breathing / grounding library (incl. crave-surfing)
Reframe ships meditations and games; most wellness-first competitors have guided breathing/grounding. SC has neural **TTS for chat but no structured meditation/breathing sessions** — the exact tool needed *during* a craving or at bedtime. Like #2, this can run fully on-device, reinforcing the privacy story.

### <a id="fr10"></a> 10. ❌ REJECTED — Audio Big Book + read-along for the literature library

> *Rejected 2026-08-01: continuous narration of full texts is functionally an audiobook — outside the "study aide, not publisher" excerpt stance; copyright must be licensed first. Revisit only with licensing in hand.*
Everything AA (free, official) and Sober Me provide **full audio Big Book + 12&12 + audio readings**. SC's reader is text-only (TTS reads *chat*, not the literature). Giving the **actual library an audiobook layer with synchronized read-along highlighting** extends the one true moat (the literature) — and it's the one place a paid/premium value prop could live (competitors sell or gate audio; the official AA app gives it away free, so format-quality + read-along is how to compete).

### <a id="fr11"></a> FR11. Personal companion memory — the AI remembers you across conversations
> *Approved 2026-09-07 (Owner): fully on-device (SharedPreferences, same pattern as FR1/FR4); no message bodies ever leave the device in normal mode, so no privacy-policy or liability change. One Flutter implementation covers Android, iPhone, and web (all three build from the same source).*
Every turn today is a stranger's turn: the assistant has no durable memory of the person — no triggers, no home group, no "we talked about Step 4 resentment inventory last week, how did that go." Competitors personalize shallowly (name + streak), but nobody offers a **transparent, user-editable memory** ("what I want my copilot to know") plus **cross-conversation continuation** ("pick up where we left off"). Design:

- **Profile** — static facts the user curates in a "What Copilot knows about me" sheet: sobriety date (already tracked locally), current step, triggers, key people (sponsor), home group, goals.
- **Durable facts** — after a chat ends, a one-shot **distillation** extracts reusable facts ("afraid of driving past the old bar", "Deciding whether to tell his wife about Step 8") into a local, editable, deletable list. Facts only; **never message bodies**.
- **Open threads** — the same distillation writes "unfinished topics" (e.g. *Step 8 amends list*) so the next new chat can offer **"Continue where we left off"** with a one-tap resume prompt that seeds retrieval and the first message.
- **Prompt plumbing** — the personal snapshot rides the existing `client_context`/`localUserMessage` "About this person" channel into both server chat and Private Mode local prompts, reusing the existing don't-recite-unprompted guardrails.
- **Controls** — per-fact edit/delete, "Forget everything," and a visible Personal Memory toggle. Privately stored, never uploaded.

Cheap to ship (no server change required), deepens every other feature, and strengthens rather than threatens the privacy moat.

---

## 4. Honorable mentions (bubbling under)

- **Guided full 12-step workbook** — only AA 12-Step Toolkit does Step 4/5/8/9 worksheets holistically; SC has the 4th-step inventory but could own the whole path.
- **Geofenced "places to avoid"** (Recovery Path's GPS triggers → alert sponsor).
- **Care-team / clinician link** (Recovery Record's patient↔therapist sync; Workit's telemedicine).
- **Apple Watch / HealthKit** device presence (Sober Time markets it).
- **Daily motivational push content** (daily tips/affirmations — cheap, high stickiness).

---

## 5. Suggested build sequence

**Approved build order (post-triage, 2026-08-01):** FR1 relapse reset → FR4 mood/journal → FR5 streaks (depends on FR1 + FR4 hooks) → FR9 meditation (optional FR5 hook).
**Follow-on (added 2026-09-07):** FR11 personal memory — approved (Owner): fully on-device, no new liability surface; ships alongside rather than in that sequence (touches chat, not tracker).

<details><summary>Original (pre-triage) sequence</summary>

**Tier 1 — safety & retention (ship first):** #1 relapse reset · #2 craving+SOS · #4 mood/journal.
**Tier 2 — motivation (high engagement, low risk):** #5 streaks · #3 calories/health · #9 meditation.
**Tier 3 — moat extension / audience:** #10 audio literature · #8 multi-substance/moderation · #7 companions · #6 community (needs a deliberate moderation decision).

</details>

---

## 6. Positioning takeaway

**Nobody is doing literature-grounded, privacy-first, crisis-capable recovery.** Top competitors do one axis each (community *or* tracking *or* clinically-rigorous). Closing the community/social/safety gaps above — *without* surrendering the on-device privacy and literature core — is where Sobriety Copilot can own territory that Sober Grid's death just vacated.
