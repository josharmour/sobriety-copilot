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
      // Two relapses; the first run (31 days) is the longest on record.
      final state = SobrietyState(
        sobrietyDate: DateTime(2026, 7, 1),
        relapses: [
          RelapseEvent(date: DateTime(2026, 2, 1), lostDays: 31),
          RelapseEvent(date: DateTime(2026, 3, 1), lostDays: 20),
        ],
      );
      expect(state.longestStreak, 31);
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
