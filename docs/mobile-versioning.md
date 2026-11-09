# Mobile release versions

`mobile_app/pubspec.yaml` is the source of truth: `version: 1.6.1+44`
means customer-visible version **1.6.1**, build **44**. Xcode's app and extension
targets are synchronized by `ios/sync_versions.rb`; Android uses Flutter's
versionName and versionCode. Keep both platforms on the same visible version
for the same release scope. Store rollout timing can differ.

## Current candidate

The user selected **1.7.0 (45)** for the current update, replacing the submitted
1.6.1 (44) candidate. The visible version is being advanced deliberately, with a
new build, validation and App Store review. This documentation does not confirm
store approval or publication. The previously verified iOS public release was
**1.5.2 (39)**.
Verify Google Play's production and testing tracks separately before release;
repository versions do not establish what is live in a store.

## Choose a release deliberately

The script no longer accepts a bare invocation. Choose one intent:

- `./scripts/release_mobile.sh --release patch`: start the next public bug-fix
  release; from 1.6.1+44 this prepares 1.6.2+45.
- `--release minor`: start a feature release, e.g. 1.7.0+45.
- `--release major`: start a deliberately major release, e.g. 2.0.0+45.
- `--version 1.8.0`: explicitly choose a higher public version.
- `--candidate`: iterate an **unpublished** release, retaining its visible
  version and increasing its build number. Never use this to reuse a published
  public version. Check both store consoles first; this script does not query
  live store state.
- `--build-only`: prepare a local beta build, increasing only the build number.
  No store uploads or Git commit/push occur. May be combined with a new-release
  selection to prepare that release locally before publication is authorized.
- `--no-bump`: exact rebuild of an existing candidate/local build. It cannot be
  used with `--release` or `--version`; a new public release needs a new build.
  Never re-upload a build number that the destination store already accepted.

Normal non-build-only runs retain the existing pipeline: iOS uploads to App
Store Connect/TestFlight; Android can upload to **production** if Play
credentials and fastlane are available; version files are committed/pushed.
These are consequential actions, not just version planning. Run only with
appropriate release authorization. For testing-only distribution, prepare with
`--build-only` and use the approved testing-track workflow instead.

After a public version ships, the next public release must use a higher visible
version. Additional beta builds before that release ships only need a higher
build number. Store release notes should state the visible version and concrete
user-facing changes; tester notes should also include the build number.

## Checks

Run `python3 -m unittest discover -s tests -p test_mobile_release_version.py -v`
and `bash -n scripts/release_mobile.sh`. Integration tests use a temporary
fixture and mocked build/signing/upload commands, never the real app or stores.
