# FR9 — Meditation / Breathing / Grounding Library — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Parent tracker:** [`feature-requests.md`](../feature-requests.md#fr9) → **FR9. Meditation / breathing / grounding library (incl. crave-surfing)** (Tier 2 — motivation, high engagement & low risk)

**Goal:** Add a library of **guided breathing / grounding / short meditation sessions** — the exact tool needed *during* a craving (ties to FR2) or at bedtime. SC has neural TTS for chat but no structured structured-session library. This can run **fully on-device**, reinforcing the privacy story.

**Architecture:** On-device content + timer-driven UI. A curated set of sessions (4-7-8 breathing, box breathing, body scan, brief calm, "surf the urge") delivered as guided audio via the **existing TTS** (`AppTts` / neural voices) or as silent timer guides. A `MeditationSession` model defines steps (inhale/hold/exhale durations + prompt text); a `MeditationPlayer` notifier drives a timed state machine with visual + TTS cues. Persist "sessions completed" locally for the streak integration (FR5). No backend.

**Tech Stack:** Flutter, Riverpod, `flutter_tts`/`AppTts` (already present), `dart:async` timers. No new dependencies.

**Privacy:** Local only. No recordings.

---

## Files

- Create: `mobile_app/lib/features/meditation/session.dart` — MeditationSession data model + curated library
- Create: `mobile_app/lib/features/meditation/player.dart` — MeditationPlayer notifier (timed state machine)
- Create: `mobile_app/lib/features/meditation/meditation_sheet.dart` — picker + player UI
- Modify: `mobile_app/lib/providers.dart` — register `meditationPlayerProvider`
- Modify: `mobile_app/lib/features/craving/craving_sheet.dart` (FR2) — "Try grounding" deep-links here
- Test: `mobile_app/test/meditation_test.dart`

---

## Task 1: MeditationSession model + curated library

**Objective:** A data model for a guided session and a small curated library (no audio files — TTS + timer based).

**Files:**
- Create: `mobile_app/lib/features/meditation/session.dart`
- Test: `mobile_app/test/meditation_test.dart`

**Step 1: Write failing test**

```dart
test('session total duration computes from steps', () {
  final s = MeditationSession(
    id: 'breath_478',
    title: '4-7-8 Breathing',
    steps: [
      MedStep(label: 'Inhale', seconds: 4),
      MedStep(label: 'Hold', seconds: 7),
      MedStep(label: 'Exhale', seconds: 8),
    ],
    cycles: 4,
  );
  expect(s.totalSeconds, 4 * (4 + 7 + 8));
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/meditation_test.dart`
Expected: FAIL — `MeditationSession` not defined.

**Step 3: Write minimal implementation**

```dart
class MedStep {
  final String label;
  final int seconds;
  const MedStep(this.label, this.seconds);
}

class MeditationSession {
  final String id;
  final String title;
  final String description;
  final List<MedStep> steps;
  final int cycles;

  const MeditationSession({required this.id, required this.title, required this.description, required this.steps, this.cycles = 1});

  int get totalSeconds => cycles * steps.fold<int>(0, (a, s) => a + s.seconds);
}
```

Curated library (all on-device, clearly wellness/non-clinical):

```dart
const kMeditations = [
  MeditationSession(id: 'breath_478', title: '4-7-8 Breathing', description: 'Calm the nervous system.', steps: [MedStep('Inhale',4), MedStep('Hold',7), MedStep('Exhale',8)], cycles: 4),
  MeditationSession(id: 'box', title: 'Box Breathing', description: 'Steady, even breath.', steps: [MedStep('Inhale',4), MedStep('Hold',4), MedStep('Exhale',4), MedStep('Hold',4)], cycles: 4),
  MeditationSession(id: 'surf_urge', title: 'Surf the Urge', description: 'Cravings pass like waves. Ride it out.', steps: [MedStep('Breathe',6), MedStep('Notice',6), MedStep('Rest',6)], cycles: 5),
  MeditationSession(id: 'body_scan', title: 'Mini Body Scan', description: 'Notice and release tension.', steps: [MedStep('Settle',10), MedStep('Soften',10), MedStep('Release',10)], cycles: 2),
];
```

**Step 4: Run test to verify pass**

Run: `flutter test test/meditation_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/meditation/session.dart mobile_app/test/meditation_test.dart
git commit -m "feat(fr9): meditation session model + curated library"
```

---

## Task 2: MeditationPlayer timed state machine

**Objective:** A notifier that drives the player: current step, seconds left, running/paused, and completion (persisted).

**Files:**
- Create: `mobile_app/lib/features/meditation/player.dart`
- Test: `mobile_app/test/meditation_test.dart`

**Step 1: Write failing test**

```dart
test('player advances through steps and completes', () async {
  final p = MeditationPlayer();
  p.load(kMeditations.first);
  p.start();
  // advance the timer manually via the internal tick (injectable clock)
  p.tick(); // consume some time
  expect(p.currentLabel, isNotNull);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/meditation_test.dart`
Expected: FAIL — `MeditationPlayer` not defined.

**Step 3: Write minimal implementation**

- `load(session)`, `start()`, `pause()`, `resume()`, `stop()`.
- Use a `Timer.periodic` (1s) that decrements the current step's remaining seconds; on zero, move to the next step (or next cycle, or complete). On complete, record a "session completed" tick (persist count to `meditation_completed_v1`) and optionally surface to FR5 streak.
- Inject a clock/tick function for testability (`void Function(void Function())? tickSink` or pass a `now`/`tick` callback) so tests don't need real time.

**Step 4: Run test to verify pass**

Run: `flutter test test/meditation_test.dart`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_app/lib/features/meditation/player.dart
git commit -m "feat(fr9): meditation player state machine"
```

---

## Task 3: Register provider

**Files:**
- Modify: `mobile_app/lib/providers.dart`

```dart
final meditationPlayerProvider =
    NotifierProvider<MeditationPlayer, MeditationSession?>(MeditationPlayer.new);
```

(Or a small state object if the notifier needs richer state — adjust the type accordingly.)

Run: `flutter analyze` — clean.

**Commit:**

```bash
git commit -am "feat(fr9): register meditation player provider"
```

---

## Task 4: Picker + player UI

**Objective:** A `MeditationSheet` listing the library and a player screen with visual cues + TTS cues.

**Files:**
- Create: `mobile_app/lib/features/meditation/meditation_sheet.dart`

**Step 1 — Library list**

Bottom sheet or dedicated screen listing `kMeditations` (title, description, total duration). Tap to load a session.

**Step 2 — Player**

Show the current step label + a breathing visual (expanding circle sized to the step's inhale/hold/exhale — no animation package needed, use an `AnimationController` or simple timed opacity/scale). Speak the step label via `AppTts` (the existing `appTtsProvider`) each time the step changes. Show a countdown, pause/resume/stop controls.

**Step 3 — FR2 hook**

In FR2's `craving_sheet.dart`, replace the placeholder "Try grounding" text with a real deep-link that opens the `surf_urge` session in this player.

**Step 4 — FR5 hook**

On session complete, call `streakProvider.notifier.recordCheckIn()` (optional) so meditating counts toward the daily streak — only if FR5 merged.

**Verification:** `flutter analyze` + `flutter test`. Manual: run a session on device; confirm TTS speaks step labels and the timer advances.

**Commit:**

```bash
git add mobile_app/lib/features/meditation/meditation_sheet.dart
git commit -m "feat(fr9): meditation library UI + player"
```

---

## Task 5: Accept-criteria + safety

**Verification:**
1. `flutter test` — all pass; `flutter analyze` — clean.
2. Manual: pick each session → plays through, TTS cues on step change, completes; backgrounding/notification-safe (timers pause gracefully on app pause via `WidgetsBindingObserver` or lifecycle hook).
3. "Surf the Urge" is reachable from the FR2 craving sheet.
4. Wellness framing only — no breathing drill should be positioned as medical treatment; keep the "not a substitute for emergency help" note for craving context.

**Commit:**

```bash
git commit -am "test(fr9): accept-criteria + lifecycle safety"
```

---

## Risks / open questions
- **TTS latency for breathing cues:** neural TTS may lag; consider a silent timer mode (visual only) as the default and TTS as opt-in, or use very short fixed-prompts. Test for jitter on-device.
- **Pause/background:** meditation must not fire recurrence timers stuck in the background — pause on app background (lifecycle observer) and resume cleanly.
- **Don't over-build:** 4–6 curated sessions is enough; avoid a large content library (YAGNI). Extend later from usage.

---

## Reviewer feedback (owner-approved review, 2026-08-01) — READ BEFORE IMPLEMENTING

**First read the "Cross-cutting" section in [FR1-relapse-tracker.md](FR1-relapse-tracker.md)** (ProviderContainer test pattern, mac Flutter SDK, package imports). FR9 has no hard dependency on the other plans — the FR5 hook is optional and gated on FR5 being merged. **Note: FR2 was rejected** — ignore every FR2 reference above (Task 4 Step 3, the craving-sheet deep-link, the files list entry for `craving_sheet.dart`). The meditation sheet's entry points are the Today sheet and the app-bar/menu, nothing else.

### Corrections to the plan
1. **The provider type in Task 3 is wrong.** `NotifierProvider<MeditationPlayer, MeditationSession?>` can't represent step/cycle/countdown. Define a real state object:
   ```dart
   class MeditationPlayerState {
     final MeditationSession? session; // null = idle
     final int cycle;                  // 0-based
     final int stepIndex;              // 0-based
     final int secondsLeft;            // within current step
     final bool running;               // false = paused or idle
     // const ctor + copyWith
   }
   final meditationPlayerProvider =
       NotifierProvider<MeditationPlayer, MeditationPlayerState>(MeditationPlayer.new);
   ```
2. **Timer ownership + disposal:** the `Timer.periodic` lives inside the notifier; cancel it in `ref.onDispose(...)` and on `stop()`. Expose a public `tick()` that the timer calls — tests drive `tick()` directly and never touch real time (this concretizes the plan's "injectable clock").
3. **TTS integration — use `appTtsProvider`, don't touch `onDone`.** `AppTts` ([tts_service_native.dart:148](../../mobile_app/lib/features/tts/tts_service_native.dart)) has a single mutable `onDone` callback shared with chat read-aloud. The player is *timer*-driven, not TTS-completion-driven, so: call `speak(label)` on step change, `stop()` when the player stops, and **never assign `onDone`** (you'd break chat read-aloud's completion handling). Be aware `speak()` internally calls `stop()` first — starting a session will silence any in-progress chat read-aloud; that's acceptable, but stop TTS explicitly when the sheet closes.
4. **Default to visual-only cues; TTS is an opt-in toggle in the player UI.** Neural voices synthesize per-sentence with real latency — a spoken "Inhale" that lands 2s into a 4s inhale is worse than silence. With TTS enabled and a neural voice installed, cue words may still lag; the visual (expanding/contracting circle + countdown) is the source of truth. Persist the toggle (`meditation_tts_v1`).
5. **Completion persistence:** `meditation_completed_v1` stores a simple count plus last-completed date. The FR5 hook (`recordCheckIn()` on completion) goes in **only if FR5 is already merged** — otherwise leave `// TODO(fr5)`.
6. **Lifecycle:** register a `WidgetsBindingObserver` in the player sheet — on `AppLifecycleState.paused`, pause the session (don't let the timer run in background); resume manually by the user, not automatically.
7. **"Surf the Urge" copy:** since FR2's craving sheet is gone, this session is the app's only in-the-moment craving tool — give it top placement in the library list, and keep the "not a substitute for emergency help — see the crisis sheet" line in its description (link to the existing crisis sheet).
8. **Session content sign-off:** the four sessions in Task 1 are approved as-is. Do not add more; do not reword the descriptions into anything clinical ("calms the nervous system" is the ceiling — no claims beyond that).
9. **Accessibility:** the breathing circle needs a text fallback — the step label + countdown must be readable by screen readers (`Semantics` labels), since a purely visual animation is invisible to TalkBack/VoiceOver users.
