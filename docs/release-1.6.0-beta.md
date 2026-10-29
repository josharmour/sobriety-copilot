# 1.6.0 (41) beta rollout

User-approved release scope: TestFlight first, then the existing Google Play testing audience. Public App Store, Google Play production and website deployment remain on hold.

## Changes

- Today, Chat, Library and You navigation is enabled by default.
- Existing check-ins, readings, saved passages, memory, meetings and settings remain the underlying feature implementations.
- Chat stays mounted across navigation, preserving unsent drafts. Opening a saved conversation selects Chat.
- No storage migration, backend URL change, package change, new permission or tester access change.
- The previous home remains available at build time with `--dart-define=DAY_HOME=false`.

## Validation

All 275 Flutter tests passed. New coverage includes production defaults, existing saved conversations, draft preservation, local check-in state, 200% text size and Flutter mobile accessibility guidelines. Targeted Dart analysis reports no issues. The prior browser review covers light/dark and mobile/desktop navigation with real feature sheets.

The iOS device archive compiled successfully (299.6 MB). Export/upload succeeded using existing signing assets, without `-allowProvisioningUpdates` or device registration. Apple reported nonfatal missing third-party framework dSYM warnings. iOS simulator interaction is blocked by existing Google ML Kit dependencies without ARM64 simulator slices required on this Mac's iOS 26+ simulators. No physical-device validation of this build is claimed.

## Beta destinations

- Apple app `6792023866`, bundle `com.sobrietycopilot.app`: existing App Store Connect Users and External Testers groups. Build 1.6.0 (41) uploaded, finished processing and attached automatically to the internal group. Added to the existing external group and submitted for beta review with automatic tester notification enabled. External availability awaits Apple review.
- Google Play app `4976341011854504375`: active Internal testing track `4701194825992468004`, existing selected `sobriety-copilot-testers` list (2 users). Closed Alpha has no releases and is not configured with testers. Existing Internal testing draft is empty; the empty draft was reused without changing the tester list. Google Play confirms release `1.6.0 (41) - Daily home beta` is Available to internal testers. Propagation to Play clients can take up to an hour or occasionally longer.

## Release workflow

`scripts/release_mobile.sh --no-bump --skip-ios --build-only` produces the signed Android AAB locally and explicitly disables store upload and Git commit/push. This avoids the legacy script's automatic production-track upload. Google Play beta upload/distribution is a separate reviewed console action. Initial attempt to run the unguarded legacy workflow was rejected by automatic approval review; no upload or Git action occurred from that rejected command.

Source integration fast-forwarded `master` to UI commit `c2bd6ce`; the pre-existing beta deployment script edit and untracked sketches/build caches were preserved. MTGA repositories and services were not touched.

Android signed AAB built successfully (178.2 MB): `~/Downloads/sobriety-copilot-1.6.0+41.aab`. SHA-256: `fe9b440cedaa9c2c85824886ebd9b746d6dcda2529397cfce4165bb23ecc4c36`. JAR signature verification succeeded. A generic live-backend smoke test returned a complete streamed answer, sources, follow-up suggestions and `done: true`, with no error event.

Build-only guard regression check passed using a temporary fixture with mock Play credentials and fastlane present: an artifact was produced, with no uploader, Xcode or Git invocation.
