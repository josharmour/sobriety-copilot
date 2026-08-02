# FR5 — Streaks + Daily Check-In Gamification — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Parent tracker:** [`feature-requests.md`](../feature-requests.md#fr5) → **FR5. Streaks + daily check-in gamification** (Tier 2 — motivation, high engagement & low risk)

**Goal:** Add a **daily check-in streak** (consecutive days the user engages) with motivational reinforcement, complementing — not replacing — SC's existing keytag milestones. Milestones are the reward; a streak feed is the engine that brings the user back daily.

**Architecture:** On-device, Riverpod + SharedPreferences. A `StreakState` (current streak count, last check-in date, best streak, and a history of daily check-in flags for the last N days). A `DailyCheckin` is recorded when the user opens/completes a daily action (reading, mood check-in via FR4, or a dedicated "I'm still here" tap). A subtle UI component (streak flame + day count) appears on the home/today surface. Best-streak interplays with FR1's relapse reset (a relapse resets the current streak; best streak persists).

**Tech Stack:** Flutter, Riverpod, SharedPreferences, `intl`. No new deps. Reads `sobrietyProvider` (FR1) and `moodProvider` (FR4) where relevant.

**Privacy:** Local only.

---

## Files

- Create: `mobile_app/lib/features/milestones/streak.dart` — StreakState + StreakNotifier + persistence
- Create: `mobile_app/lib/features/milestones/streak_card.dart` — UI (flame + count + check-in prompt)
- Modify: `mobile_app/lib/features/daily/today_sheet.dart` — add streak card + record check-in on open
- Modify: `mobile_app/lib/providers.dart` — register `streakProvider`
- Test: `mobile_app/test/streak_test.dart`

---

## Task 1: StreakState model + day logic

**Objective:** Model the streak: current count, last check-in date, best streak.

**Files:**
- Create: `mobile_app/lib/features/milestones/streak.dart`
- Test: `mobile_app/test/streak_test.dart`

**Step 1: Write failing test**

```dart
test('tapping a check-in on a new consecutive day increments streak', () {
  final s0 = StreakState(lastCheckIn: DateTime(2026, 8, 1), current: 5, best: 7);
  final s1 = s0.record(DateTime(2026, 8, 2)); // next day
  expect(s1.current, 6);
  expect(s1.best, 7);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/streak_test.dart`
Expected: FAIL — `StreakState` not defined.

**Step 3: Write minimal implementation**

```dart
class StreakState {
  final int current;
  final int best;
  final DateTime? lastCheckIn;
  final List<DateTime> history; // last N check-in days (for the grid)

  const StreakState({this.current = 0, this.best = 0, this.lastCheckIn, this.history = const []});

  /// Records a check-in on [day] (local date). Handles same-day (no-op), next-day
  /// (increment), and a gap (reset current to 1).
  StreakState record(DateTime day) {
    final d = _dateOnly(day);
    if (lastCheckIn != null && !_dateOnly(lastCheckIn!).isBefore(d)) {
      return this; // same day, no-op
    }
    final consecutive = lastCheckIn != null &&
        _dateOnly(lastCheckIn!).difference(d).inDays.abs() == 1;
    final next = consecutive ? current + 1 : 1;
    final newBest = next > best ? next : best;
    return StreakState(
      current: next,
      best: newBest,
      lastCheckIn: d,
      history: [...history.take(29), d],
    );
  }

  // toJson / fromJson ...
}
```

**Step 4: Run test to verify pass**

Run: `flutter test test/streak_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/milestones/streak.dart mobile_app/test/streak_test.dart
git commit -m "feat(fr5): StreakState with consecutive-day logic"
```

---

## Task 2: StreakNotifier + persistence

**Objective:** Notifier persisted to `streak_v1`, with `recordCheckIn()` (uses today) and `reset()` (for FR1 integration).

**Files:**
- Modify: `mobile_app/lib/features/milestones/streak.dart`
- Test: `mobile_app/test/streak_test.dart`

**Step 1: Write failing test**

```dart
test('recordCheckIn persists and resets work', () async {
  final n = StreakNotifier();
  n.state = StreakState(current: 3, best: 5, lastCheckIn: DateTime(2026, 7, 31));
  await n.recordCheckIn();
  expect(n.state.current, 4);
  await n.reset();
  expect(n.state.current, 0);
  expect(n.state.best, 5);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/streak_test.dart`
Expected: FAIL — `StreakNotifier` not defined.

**Step 3: Write minimal implementation**

`Notifier<StreakState>` backed by SharedPreferences key `streak_v1`, with `recordCheckIn()` calling `state.record(_dateOnly(DateTime.now()))`, and `reset()` zeroing `current` (keeping `best`).

**Step 4: Run test to verify pass**

Run: `flutter test test/streak_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/milestones/streak.dart
git commit -m "feat(fr5): StreakNotifier with persistence"
```

---

## Task 3: Register provider + FR1 integration

**Files:**
- Modify: `mobile_app/lib/providers.dart`
- Modify: `mobile_app/lib/features/milestones/sobriety_tracker.dart` (FR1 `logRelapse` → also reset streak)

**Step 1 — Register provider**

```dart
final streakProvider =
    NotifierProvider<StreakNotifier, StreakState>(StreakNotifier.new);
```

**Step 2 — Tie relapse reset to streak**

In FR1's `logRelapse`, after resetting sobriety date, also call `ref.read(streakProvider.notifier).reset()` so a relapse restarts the current streak while preserving best. (Do this only if FR1 has merged; otherwise leave a `TODO(fr5)` and reconcile at merge time.)

**Verification:** `flutter analyze` + `flutter test`.

**Commit:**

```bash
git commit -am "feat(fr5): register streakProvider + relapse resets current streak"
```

---

## Task 4: Streak card UI

**Objective:** A `StreakCard` showing the current streak (flame icon + "N-day streak"), best streak, and a 7/30-day dots grid.

**Files:**
- Create: `mobile_app/lib/features/milestones/streak_card.dart`

**Step 1 — Implement**

Flame/highlight styled in the app's palette (navy/cyan/gold). Show current streak, "best: N", and a horizontal row of the last 7 check-in dots (filled if check-in recorded that day). A "Check in" action calls `StreakNotifier.recordCheckIn()`.

**Step 2 — Integrate**

Add `StreakCard` to `today_sheet.dart` near the top. Also record a check-in when the user completes the daily reading or FR4 mood check-in (call `recordCheckIn()` from those completion paths).

**Verification:** `flutter analyze` + `flutter test`. Manual: see the card update daily.

**Commit:**

```bash
git add mobile_app/lib/features/milestones/streak_card.dart mobile_app/lib/features/daily/today_sheet.dart
git commit -m "feat(fr5): streak card UI + check-in triggers"
```

---

## Task 5: Motivation copy + accept-criteria

**Objective:** Add encouraging, non-shaming microcopy and verify the full loop.

**Verification:**
1. Streak copy is supportive ("You showed up for yourself N days in a row.") — never guilt-tripping on a broken streak (recovery-sensitive tone).
2. `flutter test test/streak_test.dart` — all pass.
3. `flutter analyze` — clean.
4. Manual: complete a daily action → streak increments; skip a day → streak resets to 1 but best persists; log a relapse (FR1) → current streak resets, best persists.

**Commit:**

```bash
git commit -am "feat(fr5): motivating microcopy + accept-criteria verification"
```

---

## Risks / open questions
- **What counts as a check-in?** Keep it forgiving: opening the today surface, completing a reading, or a FR4 mood check-in all count. Do not require a paid/celabratic action.
- **Gamification caution:** Streaks can backfire for someone who relapses (shame). Ensure the streak resets are framed as "you can always start again" and never punish — consistent with FR1's shame-free design. Consider hiding the streak entirely if the user enables FR1 discreet mode.
- **Best-streak double-counting with FR1:** make sure `longestStreak` (days sober) and `streak best` (check-in days) are two distinct, clearly-labeled metrics — do not conflate them.

---

## Reviewer feedback (owner-approved review, 2026-08-01) — READ BEFORE IMPLEMENTING

**First read the "Cross-cutting" section in [FR1-relapse-tracker.md](FR1-relapse-tracker.md)** (ProviderContainer test pattern, mac Flutter SDK, package imports). **Implement FR5 only after FR1 and FR4 have merged** — Task 3 and Task 4 wire into both.

### Bugs in the plan's code (must fix)
1. **Consecutive-day check is wrong.** `_dateOnly(lastCheckIn!).difference(d).inDays.abs() == 1` treats a check-in the day *before* the last one as consecutive (clock rollback → free streak increment). Use the signed forward difference:
   ```dart
   final consecutive = lastCheckIn != null &&
       d.difference(_dateOnly(lastCheckIn!)).inDays == 1;
   ```
2. **History truncation keeps the wrong end.** `[...history.take(29), d]` retains the *oldest* 29 entries and drops recent ones once full. Keep the newest 30:
   ```dart
   final h = [...history, d];
   history: h.length > 30 ? h.sublist(h.length - 30) : h,
   ```
3. **`record()` must be testable without wall-clock time.** `recordCheckIn()` should take an optional `DateTime? now` (default `DateTime.now()`) so tests pass fixed dates — the plan's own Task 2 test needs this to be deterministic.

### Design corrections
4. **There is already a streak in the app — reconcile, don't duplicate.** [today_sheet.dart:30](../../mobile_app/lib/features/daily/today_sheet.dart) surfaces `inventoryProvider.notifier.streak` (consecutive evening reviews). Two unlabeled "streaks" on the same sheet is confusing. Resolution (owner-approved): the new **check-in streak is the single user-facing streak**; completing the nightly inventory *counts as* a check-in (call `recordCheckIn()` from the inventory-save path). Rename/relabel the existing inventory streak display to feed the unified card, or remove its separate display — but keep `InventoryNotifier.streak` itself (other code may use it) and do NOT change inventory persistence.
5. **Check-in triggers (final list):** completing the daily reading, saving a nightly inventory, saving an FR4 mood entry, or the explicit "Check in" tap. **Merely opening the Today sheet does NOT count** — an ambient trigger makes the streak meaningless and the plan's "forgiving" rationale is served by having four easy triggers. `record()` is already same-day idempotent, so multiple triggers per day are safe.
6. **`reset()` semantics (FR1 integration):** zero `current`, keep `best`, **keep `history`** — past check-ins are facts; erasing them punishes, which contradicts FR1. Wire the FR1 `TODO(fr5)` in `logRelapse` to this `reset()`.
7. **Discreet mode:** don't hide the streak card (the plan's suggestion). The copy ("You showed up N days in a row") contains no recovery wording, which is exactly what discreet mode protects. Just verify no "sober/recovery" strings in the card.
8. **Broken-streak copy:** when `current` drops to 1 after a gap, show "Welcome back — day 1 of a new streak. Best: N." Never show what was lost.
9. **No flame emoji/icon if it reads as Duolingo-style pressure** — use the app's existing accent styling (see how `milestone_card.dart` styles the progress ring) rather than importing gamification iconography. Keep it calm.
