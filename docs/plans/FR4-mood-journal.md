# FR4 — Mood/Emotion Check-In + Daily Journal — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Parent tracker:** [`feature-requests.md`](../feature-requests.md#fr4) → **FR4. Mood/emotion check-in + daily journal** (Tier 1 — safety & retention)

**Goal:** Add a **daily mood/emotion check-in** ("how am I feeling") with optional free-text journaling, plus a **trend view** so the user can see emotional patterns over time. This bridges the gap between SC's structured nightly 4th-step inventory and the reflective, free-form space competitors (SoberTool's "I'm feeling…" selector, I Am Sober's daily check-in) provide.

**Architecture:** On-device, Riverpod + SharedPreferences. A `MoodEntry` (date, mood value, optional label/emotion, optional journal text) per day, one per calendar day (upsert). A `MoodNotifier` holds the list and exposes `entryFor(date)`. A `MoodSheet` provides the check-in UI with an emotion selector (curated, non-clinical labels) + optional journal textarea; a `MoodHistory` view renders a simple 30-day trend (emoji/sparkline grid or simple bar list — no charting dependency needed).

**Tech Stack:** Flutter, Riverpod, SharedPreferences, `intl`. No new dependencies. If day count / streak data matters (ties to FR5), read `sobrietyProvider`.

**Privacy:** All local. Journal entries are private ("Never sent to the server"); explicit share only via the OS share sheet (mirror the sponsor-export pattern in `inventory_sheet.dart`).

---

## Files

- Create: `mobile_app/lib/features/daily/mood_log.dart` — MoodEntry model + MoodNotifier + persistence
- Create: `mobile_app/lib/features/daily/mood_sheet.dart` — check-in UI (emotion selector + journal)
- Create: `mobile_app/lib/features/daily/mood_history.dart` — 30-day trend view
- Modify: `mobile_app/lib/features/daily/today_sheet.dart` — add mood entry + history link (docked with the existing nightly inventory)
- Modify: `mobile_app/lib/providers.dart` — register `moodProvider`
- Test: `mobile_app/test/mood_log_test.dart`

---

## Task 1: MoodEntry model + persistence

**Objective:** A per-day mood entry with serialization.

**Files:**
- Create: `mobile_app/lib/features/daily/mood_log.dart`
- Test: `mobile_app/test/mood_log_test.dart`

**Step 1: Write failing test**

```dart
test('mood entry round-trips and is keyed by date', () {
  final e = MoodEntry(
    date: DateTime(2026, 8, 1),
    mood: 4,            // 1..5 scale
    label: 'Grateful',
    journal: 'Good meeting today.',
  );
  final r = MoodEntry.fromJson(e.toJson());
  expect(r.mood, 4);
  expect(r.label, 'Grateful');
  expect(r.journal, 'Good meeting today.');
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/mood_log_test.dart`
Expected: FAIL — `MoodEntry` not defined.

**Step 3: Write minimal implementation**

```dart
class MoodEntry {
  final DateTime date;       // local calendar date (time stripped)
  final int mood;            // 1..5
  final String label;        // optional emotion label (may be empty)
  final String journal;      // optional free text (may be empty)

  const MoodEntry({required this.date, required this.mood, this.label = '', this.journal = ''});

  // toJson (date as YYYY-MM-DD) / fromJson — same date format as SobrietyState.
}
```

**Step 4: Run test to verify pass**

Run: `flutter test test/mood_log_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/daily/mood_log.dart mobile_app/test/mood_log_test.dart
git commit -m "feat(fr4): MoodEntry model with serialization"
```

---

## Task 2: MoodNotifier + upsert/query

**Objective:** A notifier backing the mood list, persisted to `mood_log_v1`, with `entryFor(date)` and `upsert(entry)`.

**Files:**
- Modify: `mobile_app/lib/features/daily/mood_log.dart`
- Test: `mobile_app/test/mood_log_test.dart`

**Step 1: Write failing test**

```dart
test('upsert replaces same-day entry and entryFor returns it', () {
  final n = MoodNotifier();
  n.upsert(MoodEntry(date: DateTime(2026, 8, 1), mood: 3, label: 'Meh'));
  n.upsert(MoodEntry(date: DateTime(2026, 8, 1), mood: 5, label: 'Great'));
  expect(n.state.length, 1);
  expect(n.entryFor(DateTime(2026, 8, 1))!.mood, 5);
  expect(n.entryFor(DateTime(2026, 8, 2)), isNull);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/mood_log_test.dart`
Expected: FAIL — `MoodNotifier` not defined.

**Step 3: Write minimal implementation**

Follow the `SavedPassagesNotifier` pattern: `Notifier<List<MoodEntry>>` persisted as JSON to `mood_log_v1`. `upsert` replaces an entry with the same local date (or appends). `entryFor(DateTime)` returns a matching entry or null.

**Step 4: Run test to verify pass**

Run: `flutter test test/mood_log_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/daily/mood_log.dart
git commit -m "feat(fr4): MoodNotifier with upsert + entryFor"
```

---

## Task 3: Register provider

**Files:**
- Modify: `mobile_app/lib/providers.dart`

```dart
final moodProvider =
    NotifierProvider<MoodNotifier, List<MoodEntry>>(MoodNotifier.new);
```

Run: `flutter analyze` — clean.

**Commit:**

```bash
git commit -am "feat(fr4): register moodProvider"
```

---

## Task 4: Mood/emotion check-in sheet

**Objective:** A `MoodSheet` with an emotion selector + optional journal + "today's mood" rendering.

**Files:**
- Create: `mobile_app/lib/features/daily/mood_sheet.dart`

**Step 1 — Emotion selector**

Curated, recovery-relevant, non-clinical labels (mirror SoberTool's selector, pruned): Grateful, Peaceful, Hopeful, Content, Calm, Okay, Restless, Anxious, Sad, Angry, Ashamed, Alone, Hopeless. Map each to a 1–5 mood value (positive ≈ 4–5, neutral ≈ 3, negative ≈ 1–2). User picks one; can also set an explicit mood value.

**Step 2 — Journal field**

Optional multi-line textarea. Save via `MoodNotifier.upsert` with today's date. Show today's existing entry if present (pre-fill).

**Step 3 — Entry point**

Add a "How am I feeling?" card + link to history in `today_sheet.dart`, docked near the nightly inventory entry. Keep the discreet/privacy copy convention.

**Verification:** `flutter analyze` + `flutter test`.

**Commit:**

```bash
git add mobile_app/lib/features/daily/mood_sheet.dart mobile_app/lib/features/daily/today_sheet.dart
git commit -m "feat(fr4): mood check-in sheet + today entry point"
```

---

## Task 5: 30-day trend view

**Objective:** A `MoodHistory` view showing the last 30 days as an emoji/sparkline grid (no chart dependency).

**Files:**
- Create: `mobile_app/lib/features/daily/mood_history.dart`

**Step 1 — Implement**

Render the last 30 calendar days as a grid of colored squares (green→yellow→red by mood value) or emoji; today outlined. Tapping a day shows that day's label + journal. Empty days render dim. No external chart package (YAGNI) — a simple `Wrap`/`GridView` of `Container`s suffices.

**Step 2 — Wire**

Open from `MoodSheet` ("View history") and from `today_sheet.dart`.

**Verification:** `flutter analyze` + `flutter test`.

**Commit:**

```bash
git add mobile_app/lib/features/daily/mood_history.dart
git commit -m "feat(fr4): 30-day mood trend view"
```

---

## Task 6: Journal export + privacy check

**Objective:** Optional explicit export of a journal entry (OS share sheet) and confirmation that nothing syncs to the server.

**Files:**
- Modify: `mobile_app/lib/features/daily/mood_sheet.dart`

**Verification:**
1. Add a "Share this entry" action using the OS share sheet (mirror `inventory_sheet.dart` sponsor export — `share_plus` is already a dependency).
2. Confirm no network call in `MoodNotifier` (it's pure SharedPreferences) — grep for `http`/`client` in the mood files; must be none.
3. `flutter analyze` clean.

**Commit:**

```bash
git commit -am "feat(fr4): journal share-to-sponsor + privacy confirmation"
```

---

## Risks / open questions
- **Emotion vocabulary:** keep it curated (small, familiar) rather than a huge taxonomy — matches the app's clean UX and avoids clinical claims. Can extend later.
- **Mood scale:** 1–5 is simple and dependency-free; a 7-point scale is an easy later change if user research warrants.
- **Relationship to FR1/FR5:** mood trend can later drive relapse-prediction-ish insights and pair with streaks; defer that coupling until FR5 lands.

---

## Reviewer feedback (owner-approved review, 2026-08-01) — READ BEFORE IMPLEMENTING

**First read the "Cross-cutting" section in [FR1-relapse-tracker.md](FR1-relapse-tracker.md)** — ProviderContainer test pattern, mac Flutter SDK, package imports. It applies verbatim here (MoodNotifier tests must use a container + `sharedPreferencesProvider` override, not `MoodNotifier()` directly).

### FR4-specific corrections
1. **Date keys: reuse the existing helper.** [today_sheet.dart](../../mobile_app/lib/features/daily/today_sheet.dart) already keys inventory entries with `dateIsoOf(now)` (from `inventory.dart`). Use `dateIsoOf` for `MoodEntry` serialization and for `entryFor`/`upsert` day-matching instead of inventing a second date-only comparison. `entryFor(DateTime)` must compare calendar dates only — never raw `DateTime` equality.
2. **Storage bounds.** Journals grow. Cap: journal text at ~5,000 chars (enforce in the UI with a counter, not a silent truncate), and the entry list at ~730 entries (drop oldest beyond 2 years). Keep the list sorted newest-first on upsert so the history view doesn't re-sort.
3. **Privacy — the journal must never reach the server.** The chat pipeline sends `client_context` (day count) to `/api/chat`. Mood/journal data must NOT be folded into `client_context` or any prompt context in this plan — if "mood-aware chat" is ever wanted, that's a separate owner decision. Add the grep check from Task 6 (`http`/`client` absent from mood files) to the accept criteria, and also grep for `clientContext`/`client_context` references.
4. **today_sheet integration:** the Today sheet is ~350 lines with the inventory card wired at [today_sheet.dart:183](../../mobile_app/lib/features/daily/today_sheet.dart). Place the mood card adjacent to the inventory entry, matching its card styling exactly. Mood check-in is a *morning/any-time* surface; the inventory is the *evening* review — copy should distinguish them ("How are you feeling right now?" vs the existing evening review).
5. **Emotion → mood mapping:** make it a `const Map<String, int>` in `mood_log.dart` (single source of truth for selector + history coloring). Keep the plan's 13 labels; they're good.
6. **Discreet mode:** read `sobrietyProvider`'s `discreet` flag; when set, the mood card title drops recovery wording (it mostly already has none — just verify no "sobriety/recovery" strings in mood UI).
7. **Share:** mirror [inventory_sheet.dart](../../mobile_app/lib/features/daily/inventory_sheet.dart)'s `share_plus` usage (already imported there at line 4). Share is per-entry and explicit-only; no "share all".
8. **Trend view:** the plan's no-dependency grid is right. Color by mood value using the app palette (not raw green/red — check how `milestone_card.dart` pulls theme tokens and match). Tap-to-expand day details is required; keep it in the same sheet (no new route).
9. **FR5 hook:** on a successful upsert for *today*, leave `// TODO(fr5): recordCheckIn()` — FR5 wires it.
