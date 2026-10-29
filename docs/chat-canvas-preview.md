# Quiet first-message chat preview

Implemented on `prototype/day-home`, based on the released `d365a64` baseline. This iteration is not deployed, merged to master, pushed or uploaded to a mobile store.

## Design

Only the empty Chat view changes. The image, quote, tracker and dense starter stack are replaced by a calm radial color field, a short heading and a centered, wider composer. Attachment and native voice input remain available. Existing explicit resume-thread and memory controls remain below the writing area.

The writing area enters over 650 ms with a small 12 px settle. After 2.4 seconds with an empty composer, three existing general starter prompts appear in staggered, softly rounded thought bubbles. They settle once and do not float or rotate. The suggestion area reserves its space, so showing or hiding it does not move the composer or scroll position. Typing dismisses the bubbles immediately; choosing one fills an editable draft and focuses the composer. Sending remains explicit.

A typed draft, caret and controller survive idle animations and tab navigation. Hidden prompts are excluded from focus, hit testing and semantics. Idle timers cancel when the tab is inactive, the app backgrounds, or the widget is disposed. Native reduced-motion/accessibility preferences and the web browser's live `prefers-reduced-motion` preference remove movement and fades. A small disposable Dart JS-interop adapter handles the browser preference because this Flutter web engine does not forward it through MediaQuery.

After the first send, the existing conversation composer and message widgets are byte-for-byte unchanged. No backend, storage schema, permissions or dependency versions changed.

## Review locally

On the Mac: **http://localhost:8770/prototype/**. Select **Chat**, pause without typing, select a bubble, edit it, then explicitly send. New conversation replays the entrance. Try light mode via the existing Settings menu.

The preview uses clearly labelled local demo replies, injected only into the temporary build copy. It does not contact the live backend; the preview CSP blocks production connections. The Settings server card therefore shows a connection error, and server-backed library/meeting features are not functional in this isolated demo. Production source continues using the existing real repository.

The loopback server is owned by session-only launchd job `com.codex.sobriety-chat-canvas-preview`. It survives closing this task/shell and runs until logout/reboot or an explicit stop. No login item is installed. The previous preview on 8769 is untouched.

```sh
bash scripts/preview_chat_canvas.sh --status
bash scripts/preview_chat_canvas.sh --stop
bash scripts/preview_chat_canvas.sh --background
```

Artifacts and logs live in `~/Library/Caches/com.codex.sobriety-chat-canvas-preview/`.

## Verification

- Flutter analysis: no issues in changed production code and new tests.
- Full Flutter suite: **283 tests passed**.
- Eight focused tests cover idle reveal/dismissal, composer position/caret stability, inactive-tab cancellation and disposal, reduced-motion semantics, suggestion-to-draft behavior, explicit first send, New conversation, constrained-height/200% text, and tap-target/label/contrast guidelines.
- Existing saved-conversation, memory/resume and draft-preserving navigation tests pass.
- Release web build passed in an isolated local temporary directory.
- Chrome visual checks: 1280×900 desktop and 390×844 mobile; light/dark; entry fade followed by idle prompts; draft dismissal; tab switching; Enter-to-send; streamed local fixture reply; New conversation; live browser reduced-motion changes. Browser test overrides were confined to the preview tab, which closed during an extension session reset; final preview was reopened at normal settings.
- Final preview listener verified on `127.0.0.1:8770`, and the exact URL opened successfully again in a fresh browser tab.
- Native physical-device/soft-keyboard testing is still a release-stage check; this task built and inspected the web prototype and exercised constrained layouts with Flutter widget tests.

## Screenshots

![Dark desktop](chat-canvas/dark-desktop.jpg)
![Light desktop](chat-canvas/light-desktop.jpg)
![Dark mobile](chat-canvas/dark-mobile.jpg)
![Light mobile](chat-canvas/light-mobile.jpg)
