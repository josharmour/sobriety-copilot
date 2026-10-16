# FR11 — Personal Companion Memory — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Parent tracker:** [`feature-requests.md`](../../feature-requests.md#fr11) → **FR11. Personal companion memory** (Approved 2026-09-07)

**Goal:** Make the assistant *personal*: it remembers durable facts about the user, can pick up unfinished topics ("threads") in a later conversation, and never stores message bodies anywhere. Everything runs on-device; the server stays a stateless pass-through (the existing `client_context` channel already guarantees it never persists personal context).

**Architecture:** Riverpod + SharedPreferences (same pattern as FR1/FR4). A `PersonalMemoryNotifier` owns a `PersonalMemory` record: `profile` (curated fields), `facts` (distilled, editable list), `threads` (open topics with timestamps). A `MemoryDistiller` runs a one-shot LLM completion at conversation end to propose facts/threads; the user reviews the *first* proposal, later proposals auto-apply with dedupe (dedupe by normalized-text similarity and `thread.hash`). A `MemorySheet` gives the user full transparency and control (edit/delete each item, "Forget everything", master toggle). ChatNotifier injects a compact snapshot into `clientContext` (server chat) and the private-mode prompt (local chat); a resume chip on the new-chat screen seeds the first message and a pinned note that also feeds retrieval.

**Tech stack:** Flutter, Riverpod, SharedPreferences, `dart:convert`, `http` (server mode only for distillation). No new dependencies. Private Mode distills with the already-loaded on-device model (`flutter_gemma`); server mode uses a tiny Ollama call. **No `src/` changes required.**

**Privacy contract (hard rules, verify with greps before merge):**
1. Never send raw conversation text anywhere beyond the normal (already-private) chat flow; distillation in server mode sends only *that conversation's* last-N turns to the local inference host (Ollama) — the product server never sees them beyond the chat call it already made, and stores nothing.
2. Snapshot injected into `clientContext` is capped (≤ 400 chars) and marked "not for verbatim recitation."
3. Facts/threads/profile never leave the device except through the prompt channels; grep for added `http`/`post` calls outside the distiller.
4. "Forget everything" wipes prefs keys `personal_memory_v1` (+ distiller cache) and shows a confirm dialog.

---

## Files

- Create: `mobile_app/lib/features/personal_memory/personal_memory.dart` — model + notifier + persistence
- Create: `mobile_app/lib/features/personal_memory/memory_distiller.dart` — one-shot fact/thread extraction (server + local backends)
- Create: `mobile_app/lib/features/personal_memory/memory_sheet.dart` — transparency + edit/delete/forget UI
- Create: `mobile_app/lib/features/personal_memory/memory_snapshot.dart` — `buildClientContextSnapshot()`, prompt formatting, dedupe
- Modify: `mobile_app/lib/features/chat/chat_notifier.dart` — inject snapshot; offer/record thread resume; run distiller on conversation end
- Modify: `mobile_app/lib/features/chat/chat_screen.dart` — "Continue where we left off" chip on empty state; memory snippet above composer
- Modify: `mobile_app/lib/features/private_mode/local_prompts.dart` — accept full personal snapshot in the "About this person" field (no signature change — caller passes more text)
- Modify: `mobile_app/lib/features/sheets/settings_sheet.dart` — Personal Memory toggle + entry point to MemorySheet
- Modify: `mobile_app/lib/providers.dart` — register `personalMemoryProvider`
- Test: `mobile_app/test/personal_memory_test.dart`
- Test: `mobile_app/test/memory_distiller_test.dart`
- Test: `mobile_app/test/memory_snapshot_test.dart`
- Test: `mobile_app/test/chat_notifier_memory_test.dart` (Riverpod notifier-test pattern, see below)

**Build note (skill):** follow the macOS web-bundle chain (`flutter build web` → `static/` → `deploy.sh`) — a cross-surface feature touching the chat path WILL stale-out if the bundle isn't rebuilt (2026-08-08 rule). Version bump in `pubspec.yaml` in the same change.

---

## Task 1: PersonalMemory model + notifier + persistence

**Objective:** Memory store with typed items, caps, CRUD, and "forget everything".

**Files:**
- Create: `mobile_app/lib/features/personal_memory/personal_memory.dart`
- Test: `mobile_app/test/personal_memory_test.dart`

**Step 1: Write failing test**

```dart
test('memory round-trips, dedupes facts, enforces caps', () {
  var m = const PersonalMemory();
  m = m.withFactAdded('Talks about missing his old driving route past the bar');
  m = m.withFactAdded('talks about missing his old driving route past the BAR'); // dup
  expect(m.facts.length, 1);
  m = m.withThreadUpdated('step-8-amends', 'Step 8 amends list', 'Working out who to write to.');
  expect(m.threads.single.title, 'Step 8 amends list');
  m = m.withFactRemoved(m.facts.single.id);
  expect(m.facts, isEmpty);
});
```

**Step 2: Run test to verify failure**

Run: `flutter test test/personal_memory_test.dart`
Expected: FAIL — `PersonalMemory` not defined.

**Step 3: Write minimal implementation**

```dart
// Stability note: keys are versioned ('personal_memory_v1'). Changing the
// schema means bumping the key and migrating, not mutating in place.
class MemoryFact { final String id; final String text; final DateTime createdAt; final String sourceConversationId; ... toJson/fromJson }
class MemoryThread { final String id; final String title; final String lastDetail; final DateTime updatedAt; final bool resolved; ... }
class PersonalProfile { String? sponsor; String? homeGroup; List<String> triggers; String? goal; ... }

class PersonalMemory {
  final PersonalProfile profile;
  final List<MemoryFact> facts;   // FIFO, cap 100 — oldest auto-drop
  final List<MemoryThread> threads; // cap 12, LRU by updatedAt
  PersonalMemory withFactAdded(String text); // normalize + similarity dedupe (>=0.9 = dup)
  PersonalMemory withThreadUpdated(String id, String title, String? detail); // upsert, bumps updatedAt
  PersonalMemory withThreadResolved(String id);
  PersonalMemory withProfile(...), withFactRemoved(id), withThreadRemoved(id);
}

class PersonalMemoryNotifier extends Notifier<PersonalMemory> {
  static const String prefsKey = 'personal_memory_v1';
  // load in build(), persist on every mutation — mirrors FR4's per-day upsert.
}
```

Caps rationale: prompt budget. 100 facts × ~60 chars ≈ 6KB stored; the *injected* snapshot is the real cap (≤400 chars, Task 4).

**Portability check (web build):** SharedPreferences on Flutter web backs to localStorage — works as-is, no code change.

**Step 4: Run test to verify pass**, then commit.

---

## Task 2: MemoryDistiller — one-shot extraction at conversation end

**Objective:** From one conversation's transcript (user+assistant turns only, last 12 turns), produce `newFacts: List<String>` and `threads: List<{id,title,detail,resolved}>`. Never runs mid-conversation; runs once when the stream finishes (ChatNotifier `finish()` path).

**Files:**
- Create: `mobile_app/lib/features/personal_memory/memory_distiller.dart`
- Test: `mobile_app/test/memory_distiller_test.dart`

**Step 1: Write failing test** (fake transport; no network)

```dart
test('distiller parses json, drops message bodies, dedupes against memory', () async {
  final d = MemoryDistiller(transport: FakeDistillTransport(
    response: '{"new_facts":["afraid of driving past the old bar"],'
        '"threads":[{"id":"step-8-amends","title":"Step 8 amends","detail":"listing people","resolved":false}]}',
  ));
  final out = await d.distill(solitaryTranscript, existing: const PersonalMemory());
  expect(out.newFacts.single, contains('afraid of driving'));
  expect(out.threads.single.title, 'Step 8 amends');
});
```

**Step 2: Run test to verify failure** (`MemoryDistiller` not defined).

**Step 3: Write minimal implementation**

```dart
abstract class DistillTransport { Future<String> complete(String prompt); }

class ServerDistillTransport implements DistillTransport {
  // POST {LLM_BASE_URL}/api/generate, non-streaming, num_predict ~= 300.
  // NOTE: this talks to the inference host (Ollama), NOT the product API —
  // only the transcript's *content-derived* JSON goes back through
  // ChatNotifier into local prefs. The product server still stores nothing.
}
class LocalDistillTransport implements DistillTransport {
  // flutter_gemma one-shot with a tiny extraction template; failure-safe.
}

class DistillResult { final List<String> newFacts; final List<MemoryThread> threads; }
class MemoryDistiller {
  Future<DistillResult> distill(List<ChatMessage> transcript, {required PersonalMemory existing});
  // Prompt: strict JSON schema, "facts the person would want remembered for
  // future conversations, stated about them in third person; unfinished
  // topics with a short next-step detail". Existing facts/threads titles are
  // provided so the model can dedupe. Throws MemoryDistillError on malformed
  // JSON — ChatNotifier catches and silently skips (never blocks chat UX).
}
```

Guardrails to encode in the prompt + parser: no message bodies verbatim (cap each fact at 120 chars), no medical/diagnostic claims, max 3 facts + 2 threads per conversation, skip conversations under 4 messages.

**Step 4: Run test to verify pass**, then commit.

---

## Task 3: Wire distillation into ChatNotifier

**Objective:** Run the distiller exactly once per finished conversation; apply results to `personalMemoryProvider`; keep the whole thing failure-safe (a distill error must never surface in chat).

**Files:**
- Modify: `mobile_app/lib/features/chat/chat_notifier.dart`
- Test: `mobile_app/test/chat_notifier_memory_test.dart`

**Key shape (match the existing notifier-test pattern):**

```dart
// Riverpod notifier-test pattern (per references/relapse-tracker-fr1.md —
// required for ALL FR plan tests):
final prefs = SharedPreferences.getInstance().then((p) => prefsProvider.overrideWithValue(p));
// container + appConfigProvider override pointing chatRepositoryProvider at a
// FakeChatRepository emitting Sources/Token/Done, + personalMemoryProvider
// pre-seeded, + distillerProvider swapped for a RecordingDistiller.
```

**Steps:**
1. In `finish()` (and in `stop()` only when at least one assistant message landed), after `_persist()`: fire-and-forget `_maybeDistill()` — guarded by `state.messages.length >= 4` and a `conversationId` not already distilled (track `distilledFor: Set<String>` in the notifier, disk-backed via prefs list).
2. Apply `DistillResult` via `personalMemoryProvider.notifier.applyDistill(result, sourceConversationId: state.conversationId)`.
3. Failure-safe: wrap in try/catch, `debugPrint` only.

**Verify:** notifier test asserts memory grows after a Done event and that a second Done on the same conversationId doesn't double-add (dedupe + distilledFor).

**Commit.**

---

## Task 4: Memory snapshot + prompt plumbing (both chat paths)

**Objective:** Compact, capped, guard-railed snapshot into `clientContext` (server) and `localUserMessage`'s "About this person" line (Private Mode), plus thread-resume prompts.

**Files:**
- Create: `mobile_app/lib/features/personal_memory/memory_snapshot.dart`
- Modify: `mobile_app/lib/features/chat/chat_notifier.dart`
- Modify: `mobile_app/lib/features/private_mode/local_prompts.dart` (doc-comment only if the field just carries more text)
- Test: `mobile_app/test/memory_snapshot_test.dart`

**Step 1: Failing test**

```dart
test('snapshot is capped and marked non-recitable', () {
  final snap = buildClientContextSnapshot(memory, maxChars: 400);
  expect(snap.length, lessThanOrEqualTo(400));
  expect(snap, contains('do not recite'));
});
test('resume prompt seeds a concrete first message', () {
  final t = MemoryThread(id: 'step-8', title: 'Step 8 amends', lastDetail: 'listing people');
  expect(resumePromptFor(t), contains('Step 8 amends'));
});
```

**Step 2–3: Implementation sketch**

```dart
String buildClientContextSnapshot(PersonalMemory m, {int maxChars = 400}) {
  // Priority order when over budget: active-thread (most recent) > triggers
  // > goal > top 2 durable facts. One line each, third person. Always ends
  // with: "(This is private memory from their device - use it to inform your
  // reply if relevant; do not recite it verbatim.)"
}

String resumePromptFor(MemoryThread t) =>
    'Pick up where we left off: we were talking about ${t.title.toLowerCase()} — ${t.lastDetail} Can you help me keep going?';
```

In `ChatNotifier.sendMessage`: replace the current day-count-only `clientContext` computation with `(dayCountLine if queryWantsDayCount else null) ?? snapshot on new-or-resumed conversations` — but **merge, not replace**: keep the day-count line when it applies and append the snapshot when the memory toggle is on and any of profile/facts/threads exist. Compose them before the existing server-side 300-char clamp — adjust that clamp to 600 in `src/server.py`'s `client_note` line **only if** the merged snapshot exceeds it (one-line change, mention in release notes; keep the repo default behavior otherwise).

In `loadConversation`/resume chip: when resuming a thread, send the resumed conversation's first message = `resumePromptFor(thread)` and pin `thread.title` into the snapshot's first line so retrieval and the model both anchor on it.

**Step 4: Run tests to pass**, then commit.

---

## Task 5: Retrieval hook for resumed threads

**Objective:** Make memory *functional*, not just persona: when a resumed thread or top facts exist, fold their key nouns into `history`-adjacent retrieval.

**Files:**
- Modify: `mobile_app/lib/features/chat/chat_notifier.dart` (already builds `history` — prepend a synthetic user turn `'[Previously]: we were working on <thread title> — <detail>'` ONLY for resumed conversations)

No server change: `_build_retrieval_query` already folds recent history turns — a resumed conversation's first synthetic turn lands there for free.

**Verify:** chat-notifier test asserts `trimmedHistory.first.text` starts with `'[Previously]:'` on resume path only.

**Commit.**

---

## Task 6: MemorySheet — transparency & control UI

**Objective:** User-visible, editable memory. No black box.

**Files:**
- Create: `mobile_app/lib/features/personal_memory/memory_sheet.dart`
- Modify: `mobile_app/lib/features/chat/chat_screen.dart` (empty state: "Continue where we left off" — most recent unresolved thread; one tap → `loadConversation` equivalent new chat seeded with `resumePromptFor`)
- Modify: `mobile_app/lib/features/sheets/settings_sheet.dart` (toggle + "What Copilot knows about me" row)
- Modify: `mobile_app/lib/providers.dart` (`personalMemoryProvider`, `memoryDistillerProvider`, solved threads filter)

**Shape:** Sections — Profile (inline-editable fields incl. current step fallback to fused server value), Facts (dismissible list, edit dialog), Threads (title + lastDetail + age; "Mark handled"), Forget-All (confirm dialog → wipe both prefs keys). Header: privacy line "Stored only on this device. Sent with your messages as context; never saved by the server."

**Verify:** `flutter analyze` 0 issues; manual walk on an emulator (add fact via chat → sheet shows it → edit → delete → forget-all).

**Commit.**

---

## Task 7: Release build chain (all three surfaces)

1. Bump version in `mobile_app/pubspec.yaml`.
2. `flutter build web --release` → `cp -R build/web/. ../static/` → sentinel-grep the new string in `static/main.dart.js`.
3. `./deploy.sh` for the web surface; APK/IPA per the skill's release recipes (JDK21 pin for Android; `flutter build ipa --release` + Transporter for TestFlight).
4. Post-deploy probe: `ssh joshu@10.0.0.100 "curl -s localhost:8090/main.dart.js | grep -c '<SENTINEL>'"` ≥ 1; `version.json` shows the new build number.

---

## Testing & verification summary

- Unit: model + dedupe + caps (Task 1), distiller parsing/guardrails (Task 2), snapshot capping (Task 4), notifier wiring/dedupe-on-re-distill (Task 3, Riverpod notifier-test pattern mandatory).
- Privacy greps before merge:
  - `grep -rn "personal_memory_v1" mobile_app/lib` → only the notifier + sheet.
  - Confirm no new `http` POST beyond `ServerDistillTransport` (inference host only).
  - `git grep client_context src/` → clamp line unchanged unless Task 4 adjusted it deliberately.
- `flutter analyze` clean; `flutter test` green; `flutter build web` succeeds (Wasm dry-run warnings from flutter_tts are pre-existing noise — only "✓ Built build/web" matters).
- Manual QA on device: chat end → fact appears in sheet; restart app → memory persists; resume chip → retrieval actually returns the previously-discussed Step section (check source chips); Private Mode → same behavior with airplane-mode ON.

## Out of scope (explicitly)

- Server-side memory of any kind (the `UserMemoryManager` SQLite path stays as-is; nothing new keys off `user_id`).
- Cross-device sync (would require a server; revisit only if Josh asks).
- Automatic "smart recall" search over past conversations (could ride on FR11's threads later; not now).
