# UI proposal review and Day Home prototype

Reviewed 2026-10-29 against committed `a919011` and the six untracked sketches in the original checkout. All six HTML proposals were rendered, and the actual committed Flutter web bundle was rendered locally with backend connections blocked. Source inspection covered the chat shell, theme tokens, daily practice, mood check-in, tracker, and associated navigation. The screenshots are design evidence, not evidence of any person's health or history.

## Recommendation

Prototype **004 The Day's navigation** with **002 Quiet Editorial's restraint**. Keep the existing chat and working feature screens. The main opportunity is discoverability, not a wholesale visual replacement or a new AI behavior model. A staged prototype costs much less than replacing the application with any HTML sketch.

The current mobile home makes starting a conversation obvious, offers rotated prompts, provides Today/Meetings shortcuts and supports both themes. Its working graph, citations, memory, tracker, daily practice, meetings, and accessible Material controls are valuable. The large lighthouse background competes with starter text in dark mode; the overflow menu contains nine destinations, and daily tasks are spread between it, shortcuts, and sheets. The designs should improve access without discarding these strengths.

| Proposal | What improves on the current UI | Tradeoff / evidence | Relative implementation cost |
| --- | --- | --- | --- |
| 001 Aurora Glass | Strong brand continuity; visible breathing, reading and check-in actions; a welcoming home | Too much space and visual weight goes to the counter. In the actual render the counter ring and milestone area clip within the hero. Muted labels on translucent surfaces, animated backgrounds, and clickable divs need work. Dark only. | Medium for a usable responsive reskin; low value from copying the decorative effects |
| 002 Quiet Editorial | Best calm reading hierarchy; body text is easier to follow without the lighthouse image; clear literature identity | The giant day count still displaces tasks. Fine uppercase metadata and pale gold/cyan text are weak. Missing accessible navigation behavior and an equivalent dark treatment. | Low–medium visual work; does not by itself solve feature navigation |
| 003 Night Beam | One prominent talk action and visible support actions reduce decision load | Voice dominates even when typing is needed; statistics have unclear meaning; animated beam/ripples distract. The sketch's Talk surface is not a functional recording control and its sponsor shortcut has no established data/permission flow. | Medium–high if voice and support integrations are real; useful as an optional focused mode |
| 004 The Day | Best predictable destinations and daily-task access; copilot remains reachable from other contexts | “Now” needs trustworthy context logic; “Story” is less explicit than “You.” Persistent support is described but not equally prominent in every rendered state. Cards mostly provide press feedback, not completed workflows. | Medium for navigation over existing sheets; high for adaptive recommendations and a full chat overlay |
| 005 The Stream | Coherent review/history of check-ins, reading and chat; appealing light editorial style | Chronology buries actionable tasks on busy days; composer modes add ambiguity; entries and week dots need more than color to explain status. Cross-feature timeline, retention and collapsed threads need a shared event model. | High as the entire app; good later history surface |
| 006 Copilot Home | Inline actions and visible memory could reduce friction for the conversation loop | “Listening,” reading progress and pattern nudges imply capabilities/state the sketch does not implement. Cards can bury user messages, and there is no stable place to browse features. Reliable triggers, dismissal, structured actions and memory consent make this the most complex direction. | Highest; explore later as opt-in cards rather than the sole navigation model |

The sketches use fixed 390px phone frames beside captions, omit a mobile viewport declaration, and do not establish responsive app layouts. Most include small 10–13px labels, incomplete keyboard semantics, and animation without reduced-motion handling. They are useful design explorations, not drop-in implementations. Contrast was assessed visually and against source colors; this is not a formal accessibility audit.

## Implemented prototype

Branch: `prototype/day-home`

Worktree: `/Users/joshu/repos/sobriety-copilot-day-home` (physical path `/Volumes/repos/sobriety-copilot-day-home`). Base: `a919011`.

- Initially opt-in `DAY_HOME`; after user approval, ordinary builds enable the new home. `--dart-define=DAY_HOME=false` retains the original chat home for rollback.
- Four explicit destinations: Today, Chat, Library, You. Today includes chat, local check-in status, the actual bundled daily reading, meditation, meetings and evening review.
- Existing mood, practice, tracker, memory, conversations, settings, saved-passage and graph flows are reused. The chat widget stays mounted, preserving drafts and conversation state across tabs.
- A persistent support icon in the app bar opens the existing crisis-resource sheet. No new clinical/support advice or phone numbers were introduced.
- Existing light/dark semantic color schemes and Material controls remain. No new fonts, package dependencies, imagery, schema or server behavior.
- At 700px available content width the reading and check-in panels form two columns; narrower layouts stack them. Content scrolls above labeled navigation. The prototype accounts for the existing 24px web footer.
- Tracker state is optional and placed under You. No invented personal details, progress percentages, streaks, adaptive “due” claims, or inferred pattern messages.

The typography/layout takes restraint from Editorial; this is not a pixel-for-pixel reproduction of its cream/serif skin. The unchanged chat surface still uses the lighthouse artwork. “Practice” is reached through existing daily practice controls rather than adding a fifth tab.

## Run locally

```bash
cd ~/repos/sobriety-copilot-day-home
bash scripts/preview_day_home.sh 8769 --background
# Open http://localhost:8769/prototype/
```

The script builds in a temporary local directory because the repo is on SMB. It copies only Dart/web sources and assets, uses cached dependencies, disables preview service-worker registration, and serves loopback only. Its CSP blocks backend connections; Google Flutter/font assets remain allowed. It does not publish releases or call deployment scripts. On macOS, `--background` copies only the preview assets into a dedicated local cache and loads a loopback-only launchd service for the current login session. It survives closing the terminal or ending a Codex turn, and stops at logout/reboot or `bash scripts/preview_day_home.sh --stop`. No login item is installed. `--status` shows the service state. Without `--background`, keep the terminal open and stop with Ctrl-C. Set `FLUTTER_BIN` if the installed SDK is elsewhere.

The verified preview is running at `http://localhost:8769/prototype/`, launched with the saved script. The initial comparison render and screenshots were made under `/tmp/sobriety-ui-review`. Both are temporary; the screenshots in this worktree are durable. Local check-ins/settings in this preview belong to that browser origin, separate from the live site. Backend-dependent chat generation, meeting search and graph loading are intentionally unavailable here; existing screens may show connection errors.

## Validation

- Dart analyzer on the changed production files and new test: **no issues**.
- Four new widget tests: **pass** — tab switching preserves an unsent draft; saved check-in state updates the home; Today/Library/You fit 390×844 at 200% text size; prototype-off preserves the original home.
- Nine existing resume-chip and starter-prompt tests: **pass**.
- Release web build with `--dart-define=DAY_HOME=true`: **pass**.
- Browser QA: current home, all six sketches, final prototype at 1280×720 and 390×844; light and dark themes; check-in opens the real sheet; Library and You navigate correctly. Visual QA found and corrected clipped bottom-navigation labels caused by the fixed web footer.
- `bash -n scripts/preview_day_home.sh`: **pass**; the saved script was also run end to end, compiled successfully, and its localhost:8769 output was inspected in the browser.

Screenshots in `ui-prototype-evidence/` include current mobile, the rendered proposals, and final prototype states. New native iOS/Android builds, real-device screen-reader testing, keyboard-on-phone interactions, and live-backend flows have not been validated. The repository's automatic release guidance is deliberately not applied to this user-requested isolated, unmerged prototype.

## Scope and next decisions

This validates navigation and information hierarchy. A full adaptive “Now,” cross-feature Story feed, chat overlay, proactive cards, visual restyling of all sheets, and runtime preference for choosing a home are later work. The most useful next user test: can someone find a check-in, a saved passage, help, and an unfinished conversation without opening overflow menus?

The original checkout remains on master at `a919011`, with its existing modified `scripts/deploy_beta.sh`, modified Flutter submodule, and untracked sketches/build caches preserved. No source index changes were intentionally made, and no service was stopped, merge/push/deploy performed, or release run. The source sketches were copied only to a temporary review directory; no uncommitted source baseline was needed for the prototype.

## Preview availability repair (2026-10-29)

The initial foreground preview process had exited and its cleanup trap had removed the temporary build. The reported localhost:8769 link consequently refused connections. The repaired launcher supports `--background`, checks that the port is free before building, and uses the dedicated `com.codex.sobriety-day-home-preview` launchd service, with assets/logs in `~/Library/Caches/com.codex.sobriety-day-home-preview/`. It is loaded for the current GUI login session, not installed as a login item.

Verified after the launcher exited: launchd reports running, Python listens only on 127.0.0.1:8769, and the exact localhost URL plus bootstrap, compiled app, font manifest, and CanvasKit WASM return HTTP 200. Tested in the Mac's actual Chrome browser: Today → Library → You → Chat → Today, plus opening/closing check-in. The page rendered successfully and no runtime errors were observed. Opening the existing mood sheet produced a nonfatal Noto missing-character font warning. Backend calls remain deliberately blocked.

The repaired preview was left open in Chrome at http://localhost:8769/prototype/. Reload the failed tab or use the new one; no terminal command is needed while the current login session continues. After logout/reboot, rerun the background command above.

## Approved production rollout (2026-10-29)

The user approved rollout and publication to both app stores. The new home is enabled by default, and saved conversations opened from the hamburger now visibly select Chat. The redundant tappable app title is disabled in the new home; the labeled New Conversation button remains. Storage keys, backend URLs, package dependencies, privacy behavior and native app IDs are unchanged.

Validation: all 275 Flutter tests pass, including seven new home tests covering production defaults, existing saved conversation compatibility, mobile accessibility guidelines, draft preservation, saved check-ins, large text, and the rollback flag. Targeted Dart analysis reports no issues. The native iOS simulator build is blocked by existing Google ML Kit dependencies without ARM64 simulator slices on iOS 26+, so native simulator interaction has not been verified. Store build/submission status is tracked separately; no submission is implied by this design review.
