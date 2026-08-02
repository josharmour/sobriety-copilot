# FR1 — Relapse Tracking with Shame-Free Day-Reset — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Parent tracker:** [`feature-requests.md`](../feature-requests.md#fr1) → **FR1. Relapse tracking with a shame-free day-reset** (Tier 1 — safety & retention, ship first)

**Goal:** Let a user log a relapse, reset today's counter without shame, keep full history/stats (previous best streak, total relapses, longest streak), and restart cleanly — with a gentle, non-punishing UX that makes the app *more* useful exactly when the user needs it most.

**Architecture:** Purely on-device. Extend the existing `SobrietyState` / `SobrietyNotifier` (Riverpod + SharedPreferences, `mobile_app/lib/features/milestones/sobriety_tracker.dart`) to persist a **relapse event log** and derived streak fields. A relapse "resets" the running streak but never deletes history — the old best streak is preserved and the user receives an encouraging, shame-free confirmation + a link to crisis/craving support (ties into FR2). No backend changes.

**Tech Stack:** Flutter, Riverpod (`Notifier`/`NotifierProvider`), SharedPreferences, `intl` (dates). No new dependencies.

**Privacy:** Everything stays local, consistent with the existing design contract ("Never sent to the server"). No PII leaves the device.

---

## Files

- Modify: `mobile_app/lib/features/milestones/sobriety_tracker.dart` — data model + notifier
- Create: `mobile_app/lib/features/milestones/relapse_log.dart` — relapse event model + persistence
- Modify: `mobile_app/lib/features/milestones/milestone_card.dart` — display surface (new "history" card)
- Modify: `mobile_app/lib/features/sheets/settings_sheet.dart` — "Log a relapse" action + history view entry
- Test: `mobile_app/test/sobriety_tracker_test.dart` (new or extended)

---

## Task 1: Define the RelapseEvent model

**Objective:** A value type capturing one relapse: date, optional note, optional trigger, and the streak length that was lost.

**Files:**
- Create: `mobile_app/lib/features/milestones/relapse_log.dart`

**Step 1: Write failing test**

```dart
// mobile_app/test/sobriety_tracker_test.dart
test('RelapseEvent serializes and round-trips', () {
  final e = RelapseEvent(
    date: DateTime(2026, 8, 3),
    note: 'stress at work',
    trigger: 'craving',
    lostDays: 92,
  );
  final restored = RelapseEvent.fromJson(e.toJson());
  expect(restored.date, e.date);
  expect(restored.note, 'stress at work');
  expect(restored.lostDays, 92);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: FAIL — `RelapseEvent` is not defined.

**Step 3: Write minimal implementation**

```dart
// mobile_app/lib/features/milestones/relapse_log.dart
class RelapseEvent {
  final DateTime date;      // local calendar date of the relapse
  final String note;        // optional free text (may be empty)
  final String trigger;     // optional trigger tag (may be empty)
  final int lostDays;       // running streak length lost by this relapse

  const RelapseEvent({
    required this.date,
    this.note = '',
    this.trigger = '',
    required this.lostDays,
  });

  Map<String, dynamic> toJson() => {
        'date': '${date.year.toString().padLeft(4, '0')}-'
            '${date.month.toString().padLeft(2, '0')}-'
            '${date.day.toString().padLeft(2, '0')}',
        'note': note,
        'trigger': trigger,
        'lostDays': lostDays,
      };

  factory RelapseEvent.fromJson(Map<String, dynamic> json) {
    final raw = json['date'] as String?;
    return RelapseEvent(
      date: DateTime.tryParse(raw ?? '') ?? DateTime.now(),
      note: json['note'] as String? ?? '',
      trigger: json['trigger'] as String? ?? '',
      lostDays: json['lostDays'] as int? ?? 0,
    );
  }
}
```

**Step 4: Run test to verify pass**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/milestones/relapse_log.dart mobile_app/test/sobriety_tracker_test.dart
git commit -m "feat(fr1): add RelapseEvent model with serialization"
```

---

## Task 2: Add relapse history + best streak to SobrietyState

**Objective:** Extend `SobrietyState` with a list of relapse events and derived stats (best streak, total relapses) without breaking existing JSON.

**Files:**
- Modify: `mobile_app/lib/features/milestones/sobriety_tracker.dart`
- Test: `mobile_app/test/sobriety_tracker_test.dart`

**Step 1: Write failing test**

```dart
test('best streak accounts for relapses', () {
  final state = SobrietyState(
    sobrietyDate: DateTime(2026, 1, 1),
    relapses: [
      RelapseEvent(date: DateTime(2026, 2, 1), lostDays: 31),
      RelapseEvent(date: DateTime(2026, 3, 1), lostDays: 20),
    ],
  );
  // Current streak from Mar 1 -> now; best was the 31-day run.
  expect(state.longestStreak, greaterThanOrEqualTo(31));
  expect(state.totalRelapses, 2);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: FAIL — `relapses`, `longestStreak`, `totalRelapses` don't exist.

**Step 3: Write minimal implementation**

Add fields to `SobrietyState`:

```dart
final List<RelapseEvent> relapses;   // history, never deleted

int get totalRelapses => relapses.length;

/// Longest continuous sober run on record. NaN-proof; 0 when untracked.
int get longestStreak {
  if (relapses.isEmpty) return daysSober;
  var max = 0;
  var cursor = sobrietyDate;
  for (final r in relapses) {
    if (cursor != null) {
      final len = r.date.difference(cursor).inDays;
      if (len > max) max = len;
    }
    cursor = r.date;
  }
  if (cursor != null) {
    final tail = _dateOnly(DateTime.now()).difference(cursor).inDays;
    if (tail > max) max = tail;
  }
  return max;
}
```

Update the `const` constructor, `copyWith`, `fromJson`, `toJson`, and the `prefsKey` bump to `sobriety_tracker_v2` (see Task 3 for migration).

**Step 4: Run test to verify pass**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/milestones/sobriety_tracker.dart
git commit -m "feat(fr1): add relapse history and best/longest-streak stats"
```

---

## Task 3: Persist returns-serialized relapses (JSON v2 migration)

**Objective:** Persist the relapse list and gracefully migrate `sobriety_tracker_v1` → `sobriety_tracker_v2` (old JSON lacks `relapses`).

**Files:**
- Modify: `mobile_app/lib/features/milestones/sobriety_tracker.dart`

**Step 1: Write failing test**

```dart
test('missing relapses field migrates to empty list', () {
  final state = SobrietyState.fromJson({'sobrietyDate': '2026-01-01', 'discreet': false});
  expect(state.relapses, isEmpty);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: FAIL — `fromJson` doesn't handle a missing `relapses` key.

**Step 3: Write minimal implementation**

In `fromJson`, parse `relapses`:

```dart
final rawRelapses = json['relapses'];
final relapses = rawRelapses is List
    ? rawRelapses
        .whereType<Map>()
        .map((m) => RelapseEvent.fromJson(Map<String, dynamic>.from(m)))
        .toList()
    : <RelapseEvent>[];
```

Add `'relapses': relapses.map((e) => e.toJson()).toList()` to `toJson`, and support it in `copyWith` (add `List<RelapseEvent>? relapses`).

Update `static const String prefsKey = 'sobriety_tracker_v2';`. In `SobrietyNotifier.build()`, if old key present, load it, set `relapses` to `[]`, then save under the new key (one-time migration).

**Step 4: Run test to verify pass**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/milestones/sobriety_tracker.dart
git commit -m "feat(fr1): persist relapse history with v2 JSON migration"
```

---

## Task 4: Add `logRelapse` action to SobrietyNotifier

**Objective:** Wire a notifier method that records a relapse: computes the lost streak, appends the event, and resets `sobrietyDate` to today (non-punishing restart). Never clears history.

**Files:**
- Modify: `mobile_app/lib/features/milestones/sobriety_tracker.dart`

**Step 1: Write failing test**

```dart
test('logRelapse records event and resets to today', () async {
  final n = SobrietyNotifier();
  n.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
  await n.logRelapse(note: 'slip', trigger: 'stress');
  expect(n.state.totalRelapses, 1);
  expect(n.state.relapses.first.note, 'slip');
  // sobrietyDate reset to today's calendar date
  final today = DateTime.now();
  expect(n.state.sobrietyDate!.year, today.year);
  expect(n.state.sobrietyDate!.month, today.month);
  expect(n.state.sobrietyDate!.day, today.day);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: FAIL — `logRelapse` not defined.

**Step 3: Write minimal implementation**

```dart
Future<void> logRelapse({String note = '', String trigger = ''}) async {
  final lost = state.daysSober;
  final event = RelapseEvent(
    date: _dateOnly(DateTime.now()),
    note: note,
    trigger: trigger,
    lostDays: lost,
  );
  state = SobrietyState(
    sobrietyDate: _dateOnly(DateTime.now()),
    discreet: state.discreet,
    dailySpendCents: state.dailySpendCents,
    relapses: [...state.relapses, event],
  );
  await _persist();
}
```

**Step 4: Run test to verify pass**

Run: `flutter test test/sobriety_tracker_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/milestones/sobriety_tracker.dart
git commit -m "feat(fr1): add logRelapse action that resets without deleting history"
```

---

## Task 5: Shame-free UI — relapse confirmation + history view

**Objective:** A UI surface where the user can log a relapse (optional note/trigger) and see their history + best streak, framed in non-judgmental language with a link to support.

**Files:**
- Modify: `mobile_app/lib/features/milestones/milestone_card.dart`
- Modify: `mobile_app/lib/features/sheets/settings_sheet.dart`

**Step 1 — Add history card to milestone_card.dart**

Render when `relapses.isNotEmpty`:
- "Longest streak: N days"
- "Relapses: N — each one taught you something. The journey continues today."
- List of past relapses (date + note + lost days).

**Step 2 — Add "Log a relapse" entry in settings_sheet.dart**

A discreet entry ("Log a relapse — restart today's count") that opens a dialog with an optional note + trigger, and a **confirm** that is gentle ("This resets today's count. Your history and longest streak are kept."). On confirm, call `ref.read(sobrietyProvider.notifier).logRelapse(...)` and show a supportive snackbar + link to the crisis sheet.

**Verification:** Run `flutter analyze` (no new errors) and `flutter test test/sobriety_tracker_test.dart`.

**Commit:**

```bash
git add mobile_app/lib/features/milestones/milestone_card.dart mobile_app/lib/features/sheets/settings_sheet.dart
git commit -m "feat(fr1): shame-free relapse logging UI + history view"
```

---

## Task 6: Widget + Accept-Criteria verification

**Files:** manual QA on device + `flutter test`

**Verification steps:**
1. `flutter test test/sobriety_tracker_test.dart` — all pass.
2. `flutter analyze` — clean.
3. On device: set a sobriety date, log a relapse with a note → today's count resets to Day 0, history shows the event, longest streak preserved.
4. Restart the app → relapse history persists.
5. Confirm no recovery wording leaks to the lock screen (relapse logging is intentionally out of the discreet notification paths). See `reminders_native.dart` for the "discreet copy" convention and keep it.

**Commit:**

```bash
git commit -am "test(fr1): accept-criteria verification"
```

---

## Risks / open questions
- **Streak semantics:** some competitors keep "best streak" separate from "current streak"; Task 2 computes `longestStreak` correctly, but confirm product desire for a visible "current streak" vs simple day counter. FR5 (streaks) extends this.
- **Trigger taxonomy:** keep free-text + a small suggestion list (stress, social, craving, habit, celebration) — do not over-engineer.
- **Backwards migration:** v1→v2 migration in Task 3 must be tested with a real old prefs payload.

---

## Reviewer feedback (owner-approved review, 2026-08-01) — READ BEFORE IMPLEMENTING

Verified against the actual code in this clone. These corrections override the plan text above where they conflict.

### Cross-cutting (applies to all four approved plans)
1. **Work in this clone** (`/Users/joshu/development/sobriety-copilot`), branch off master. The vendored `../flutter` SDK is Linux-only — use the local **mac** Flutter SDK for `flutter test` / `flutter analyze`.
2. **Notifier tests need a ProviderContainer.** The plan's tests instantiate notifiers directly (`SobrietyNotifier()`, then set `.state`) — that does not work with Riverpod `Notifier`s, and `sharedPreferencesProvider` ([providers.dart](../../mobile_app/lib/providers.dart)) throws unless overridden. Test pattern:
   ```dart
   SharedPreferences.setMockInitialValues({});
   final prefs = await SharedPreferences.getInstance();
   final container = ProviderContainer(overrides: [
     sharedPreferencesProvider.overrideWithValue(prefs),
   ]);
   final notifier = container.read(sobrietyProvider.notifier);
   ```
   Rewrite the plan's test snippets to this pattern (assert intent stays the same).
3. **Widget-sync in tests:** `SobrietyNotifier._persist()` calls `syncSobrietyWidget` (platform channel). Call `TestWidgetsFlutterBinding.ensureInitialized()`; if `home_widget` throws `MissingPluginException` in tests, the sync helper likely already swallows it — verify, and if not, wrap the sync call in try/catch (matching the "no-op on surfaces without widgets" doc comment) rather than mocking.
4. **Imports:** package-style (`package:sobriety_copilot_mobile/...`), matching every existing file.
5. `flutter analyze` must stay clean; commit per task with the plan's message prefixes.

### FR1-specific corrections
1. **Drop the v1→v2 prefs-key migration (Task 3's key bump).** Keep `prefsKey = 'sobriety_tracker_v1'`. `fromJson` defaulting a missing `relapses` key to `[]` is the entire migration — a new key + copy-over adds a failure mode for nothing. Keep the "missing field → empty list" test; delete the key-rename work.
2. **The `longestStreak` cursor-walk in Task 2 is wrong — replace it.** It walks from `sobrietyDate`, but `logRelapse` *resets* `sobrietyDate` on every relapse, so the walk's first segment measures from the *latest restart*, not the original start; historical run lengths are only preserved in each event's `lostDays`. Correct and simpler:
   ```dart
   int get longestStreak {
     var best = daysSober; // current run
     for (final r in relapses) {
       if (r.lostDays > best) best = r.lostDays;
     }
     return best;
   }
   ```
   Also don't assume `relapses` is date-sorted; append order is fine with this implementation.
3. **`logRelapse` must use `copyWith`, not a raw constructor.** The plan's Task 4 builds `SobrietyState(...)` field-by-field — it silently drops any field added later. Add `relapses` to `copyWith` and write:
   ```dart
   state = state.copyWith(
     sobrietyDate: _dateOnly(DateTime.now()),
     relapses: [...state.relapses, event],
   );
   ```
4. **Guard the untracked case:** if `sobrietyDate == null`, `logRelapse` should start tracking today with `lostDays: 0` (user's first interaction may be "I slipped"). Add a test.
5. **Same-day double-log:** allow it (two events, second has `lostDays: 0`). No de-dupe logic.
6. **Serialization:** reuse the existing date-only ISO format from `SobrietyState.toJson` (see [sobriety_tracker.dart:146](../../mobile_app/lib/features/milestones/sobriety_tracker.dart)); `_dateOnly` already exists in that file — don't redefine it in `relapse_log.dart` (import or pass date-only values in).
7. **Widget after relapse:** no widget-code change needed — `_persist()` re-syncs. Manually verify the home widget shows Day 0 after logging.
8. **Discreet mode:** if `state.discreet`, the history card and dialog must avoid the word "relapse" in ambient UI ("Restart log" / "Day count restarted"). Full wording is fine *inside* the explicit dialog flow.
9. **FR5 hook:** leave `// TODO(fr5): reset check-in streak` in `logRelapse`; FR5's Task 3 wires it.
10. **Milestone-card entry point:** in addition to the Settings entry, when tracking is active put a low-key "Slipped? Restart without losing your history" affordance on the tracker editor (not on the always-visible card — don't advertise relapse on the daily surface).
