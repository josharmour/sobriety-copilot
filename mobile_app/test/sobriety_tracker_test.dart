// Tests for the FR1 relapse-tracking feature: RelapseEvent model,
// SobrietyState relapse history + derived stats, serialization/migration,
// and the SobrietyNotifier.logRelapse action.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/milestones/relapse_log.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  /// Builds a [ProviderContainer] with an isolated in-memory prefs store, and
  /// returns the ready-to-use [SobrietyNotifier].
  ///
  /// Notifiers cannot be instantiated directly (Riverpod Notifier pattern);
  /// they are always resolved through the container with
  /// `sharedPreferencesProvider` overridden.
  Future<SobrietyNotifier> makeNotifier() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final container = ProviderContainer(overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
    ]);
    addTearDown(container.dispose);
    return container.read(sobrietyProvider.notifier);
  }

  // ── Task 1: RelapseEvent model ────────────────────────────────────────

  group('RelapseEvent', () {
    test('serializes and round-trips', () {
      final e = RelapseEvent(
        date: DateTime(2026, 8, 3),
        note: 'stress at work',
        trigger: 'craving',
        lostDays: 92,
      );
      final restored = RelapseEvent.fromJson(e.toJson());
      expect(restored.date, DateTime(2026, 8, 3));
      expect(restored.note, 'stress at work');
      expect(restored.trigger, 'craving');
      expect(restored.lostDays, 92);
    });

    test('serializes date in date-only ISO format', () {
      final e = RelapseEvent(date: DateTime(2026, 8, 3), lostDays: 1);
      expect(e.toJson()['date'], '2026-08-03');
    });

    test('defaults missing optional fields', () {
      final restored = RelapseEvent.fromJson(
          {'date': '2026-08-03', 'lostDays': 5});
      expect(restored.note, '');
      expect(restored.trigger, '');
      expect(restored.lostDays, 5);
    });
  });

  // ── Task 2: relapse history + best/longest-streak stats ───────────────

  group('SobrietyState relapse stats', () {
    test('best streak accounts for relapses', () {
      final state = SobrietyState(
        sobrietyDate: DateTime(2026, 1, 1),
        relapses: [
          RelapseEvent(date: DateTime(2026, 2, 1), lostDays: 31),
          RelapseEvent(date: DateTime(2026, 3, 1), lostDays: 20),
        ],
      );
      // Current streak from day reset -> now; best was the 31-day run.
      expect(state.longestStreak, greaterThanOrEqualTo(31));
      expect(state.totalRelapses, 2);
    });

    test('longestStreak uses lostDays history when current run is shorter',
        () {
      // Two relapses; the first run (31 days) is the longest on record. The
      // current run (from 2026-07-01) is 31 days on 2026-08-01, so history
      // still wins; a fixed "now" keeps this deterministic regardless of the
      // machine's wall clock.
      final state = SobrietyState(
        sobrietyDate: DateTime(2026, 7, 1),
        relapses: [
          RelapseEvent(date: DateTime(2026, 2, 1), lostDays: 31),
          RelapseEvent(date: DateTime(2026, 3, 1), lostDays: 20),
        ],
      );
      final now = DateTime(2026, 8, 1);
      expect(state.longestStreakAt(now), 31);
    });

    test('longestStreak without relapses equals current daysSober', () {
      final state =
          SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      expect(state.totalRelapses, 0);
      expect(state.longestStreak, state.daysSober);
    });

    test('longestStreak is 0 when untracked', () {
      const state = SobrietyState();
      expect(state.longestStreak, 0);
      expect(state.totalRelapses, 0);
    });

    test('daysSober counts calendar days across a DST spring-forward', () {
      // sobriety starts Saturday 2026-03-07; "now" is Monday 2026-03-09,
      // straddling the US spring-forward (Mar 8). Calendar answer is 2 days;
      // a local-midnight diff would undercount to 1 in a DST timezone.
      final state =
          SobrietyState(sobrietyDate: DateTime(2026, 3, 7));
      expect(state.daysSoberAt(DateTime(2026, 3, 9)), 2);
      expect(state.daysSoberAt(DateTime(2026, 3, 8)), 1);
    });

    test('daysSober is 0 before the sobriety date and on the date itself', () {
      final state =
          SobrietyState(sobrietyDate: DateTime(2026, 5, 10));
      expect(state.daysSoberAt(DateTime(2026, 5, 10)), 0);
      expect(state.daysSoberAt(DateTime(2026, 5, 9)), 0);
      expect(state.daysSoberAt(DateTime(2026, 5, 20)), 10);
    });
  });

  // ── Task 3: serialization / migration ─────────────────────────────────

  group('SobrietyState relapses serialization', () {
    test('missing relapses field migrates to empty list', () {
      final state = SobrietyState.fromJson(
          {'sobrietyDate': '2026-01-01', 'discreet': false});
      expect(state.relapses, isEmpty);
    });

    test('relapses round-trip through toJson/fromJson', () {
      final state = SobrietyState(
        sobrietyDate: DateTime(2026, 1, 1),
        relapses: [
          RelapseEvent(
              date: DateTime(2026, 2, 1), note: 'slip', lostDays: 31),
        ],
      );
      final restored = SobrietyState.fromJson(state.toJson());
      expect(restored.totalRelapses, 1);
      expect(restored.relapses.single.note, 'slip');
      expect(restored.relapses.single.lostDays, 31);
      expect(restored.discreet, state.discreet);
    });

    test('toJson preserves a missing relapses absence cleanly', () {
      final state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      final json = state.toJson();
      expect(json['relapses'], isEmpty);
    });
  });

  // ── Task 4: logRelapse action ─────────────────────────────────────────

  group('logRelapse', () {
    test('records event and resets to today', () async {
      final n = await makeNotifier();
      n.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));

      await n.logRelapse(note: 'slip', trigger: 'stress');

      expect(n.state.totalRelapses, 1);
      expect(n.state.relapses.first.note, 'slip');
      expect(n.state.relapses.first.trigger, 'stress');
      // Lost days = the running streak at the time (from Jan 1).
      expect(n.state.relapses.first.lostDays, greaterThanOrEqualTo(200));
      // sobrietyDate reset to today's calendar date.
      final today = DateTime.now();
      expect(n.state.sobrietyDate!.year, today.year);
      expect(n.state.sobrietyDate!.month, today.month);
      expect(n.state.sobrietyDate!.day, today.day);
    });

    test('preserves fields not touched by logRelapse', () async {
      final n = await makeNotifier();
      n.state = SobrietyState(
        sobrietyDate: DateTime(2026, 1, 1),
        discreet: true,
        dailySpendCents: 1500,
      );

      await n.logRelapse();

      expect(n.state.discreet, isTrue);
      expect(n.state.dailySpendCents, 1500);
    });

    test('starts tracking today when untracked (lostDays 0)', () async {
      final n = await makeNotifier();
      n.state = const SobrietyState();

      await n.logRelapse();

      expect(n.state.totalRelapses, 1);
      expect(n.state.relapses.first.lostDays, 0);
      final today = DateTime.now();
      expect(n.state.sobrietyDate!.year, today.year);
      expect(n.state.sobrietyDate!.month, today.month);
      expect(n.state.sobrietyDate!.day, today.day);
    });

    test('allows same-day double-log (no dedupe)', () async {
      final n = await makeNotifier();
      n.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));

      await n.logRelapse();
      await n.logRelapse();

      expect(n.state.totalRelapses, 2);
      // The second same-day log loses 0 days.
      expect(n.state.relapses.last.lostDays, 0);
    });

    test('clearRelapses removes all history but keeps tracking state',
        () async {
      final n = await makeNotifier();
      n.state = SobrietyState(
        sobrietyDate: DateTime(2026, 1, 1),
        discreet: true,
        dailySpendCents: 1500,
      );
      await n.logRelapse(note: 'slip', trigger: 'stress');
      await n.logRelapse(note: 'another');
      // logRelapse resets the sobriety date to today; capture it so we can
      // assert clearRelapses leaves the tracker (sans history) untouched.
      final resetDate = n.state.sobrietyDate;

      // Erasing must not destroy the all-time best-streak record.
      final bestBefore = n.state.longestStreak;

      await n.clearRelapses();

      expect(n.state.totalRelapses, 0);
      expect(n.state.relapses, isEmpty);
      // The rest of the tracker state is untouched.
      expect(n.state.sobrietyDate, resetDate);
      expect(n.state.isTracking, isTrue);
      expect(n.state.discreet, isTrue);
      expect(n.state.dailySpendCents, 1500);
      // The longest-streak record survives the erase (as a bare number).
      expect(n.state.longestStreak, bestBefore);
      expect(n.state.bestStreakDays, bestBefore);
    });

    test('clearRelapses preserves the longest-streak record across a reload',
        () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final container = ProviderContainer(overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ]);
      addTearDown(container.dispose);
      final n = container.read(sobrietyProvider.notifier);
      // A historical 300-day run recorded on the event, then a short run.
      n.state = SobrietyState(
        sobrietyDate: DateTime(2026, 7, 30),
        relapses: [
          RelapseEvent(date: DateTime(2026, 7, 30), lostDays: 300),
        ],
      );
      // Fixed "now" via the test seam — clearRelapses must not depend on the
      // real wall clock or this test becomes a time bomb.
      await n.clearRelapses(now: DateTime(2026, 8, 2));
      expect(n.state.longestStreakAt(DateTime(2026, 8, 2)), 300);

      final container2 = ProviderContainer(overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ]);
      addTearDown(container2.dispose);
      final n2 = container2.read(sobrietyProvider.notifier);
      expect(n2.state.relapses, isEmpty);
      expect(n2.state.bestStreakDays, 300);
      expect(n2.state.longestStreakAt(DateTime(2026, 8, 2)), 300);
    });

    test('clearBestStreak erases the preserved record', () async {
      final n = await makeNotifier();
      n.state = SobrietyState(
        sobrietyDate: DateTime(2026, 1, 1),
        relapses: [
          RelapseEvent(date: DateTime(2026, 1, 1), lostDays: 300),
        ],
      );
      await n.clearRelapses(now: DateTime(2026, 8, 2));
      expect(n.state.bestStreakDays, 300);

      await n.clearBestStreak();
      expect(n.state.bestStreakDays, 0);
      // Jan 1 -> Aug 2 2026 is 213 days: the record is gone, only the
      // current run remains.
      expect(n.state.longestStreakAt(DateTime(2026, 8, 2)), 213);
    });

    test('fromJson defaults bestStreakDays to 0 for pre-existing data', () {
      final s = SobrietyState.fromJson(const {
        'sobrietyDate': '2026-01-01',
        'discreet': false,
      });
      expect(s.bestStreakDays, 0);
      final bad = SobrietyState.fromJson(const {
        'sobrietyDate': '2026-01-01',
        'bestStreakDays': 'oops',
      });
      expect(bad.bestStreakDays, 0);
    });

    test('clearRelapses persists across a reload', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final container = ProviderContainer(overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ]);
      final n = container.read(sobrietyProvider.notifier);
      n.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      await n.logRelapse(note: 'slip');
      await n.clearRelapses();

      final container2 = ProviderContainer(overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ]);
      addTearDown(container.dispose);
      addTearDown(container2.dispose);
      final n2 = container2.read(sobrietyProvider.notifier);
      expect(n2.state.totalRelapses, 0);
    });

    test('persists relapse history across a reload', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final container = ProviderContainer(overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ]);
      final n = container.read(sobrietyProvider.notifier);
      n.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      await n.logRelapse(note: 'slip');

      // Simulate a restart: read the notifier fresh from the same prefs.
      final container2 = ProviderContainer(overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
      ]);
      addTearDown(container.dispose);
      addTearDown(container2.dispose);
      final n2 = container2.read(sobrietyProvider.notifier);
      expect(n2.state.totalRelapses, 1);
      expect(n2.state.relapses.first.note, 'slip');
    });
  });
}
