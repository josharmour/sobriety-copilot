// Tests for the FR5 check-in streak: StreakState day logic, serialization,
// StreakNotifier persistence/reset, and the cross-feature check-in triggers
// (evening review, mood save, meditation completion) + FR1 relapse reset.
//
// Follows the cross-cutting rule: notifiers are exercised through a
// ProviderContainer with a sharedPreferencesProvider override — never
// instantiated directly.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/daily/inventory.dart';
import 'package:sobriety_copilot_mobile/features/daily/mood_log.dart';
import 'package:sobriety_copilot_mobile/features/meditation/player.dart';
import 'package:sobriety_copilot_mobile/features/meditation/session.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/features/milestones/streak.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

class _FakeMedTts implements MedTts {
  @override
  Future<void> speak(String text) async {}

  @override
  Future<void> stop() async {}
}

Future<ProviderContainer> _container({_FakeMedTts? tts}) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      if (tts != null) medTtsProvider.overrideWithValue(tts),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('StreakState.record day logic', () {
    test('next-day check-in increments the streak, best untouched', () {
      final s0 = StreakState(
        current: 5,
        best: 7,
        lastCheckIn: DateTime(2026, 8, 1),
        history: [DateTime(2026, 8, 1)],
      );
      final s1 = s0.record(DateTime(2026, 8, 2));
      expect(s1.current, 6);
      expect(s1.best, 7);
      expect(s1.lastCheckIn, DateTime(2026, 8, 2));
    });

    test('first-ever check-in starts at 1', () {
      const s0 = StreakState();
      final s1 = s0.record(DateTime(2026, 8, 2, 14, 30));
      expect(s1.current, 1);
      expect(s1.best, 1);
      expect(s1.history, [DateTime(2026, 8, 2)]);
    });

    test('same-day repeat is a no-op (identical state)', () {
      final s0 = const StreakState().record(DateTime(2026, 8, 2, 8));
      final s1 = s0.record(DateTime(2026, 8, 2, 22));
      expect(identical(s0, s1), isTrue);
    });

    test('clock rollback (earlier day) is a no-op — cannot inflate', () {
      final s0 = const StreakState().record(DateTime(2026, 8, 2));
      final s1 = s0.record(DateTime(2026, 8, 1));
      expect(identical(s0, s1), isTrue);
      expect(s1.current, 1);
    });

    test('a gap resets current to 1 and keeps best', () {
      final s0 = StreakState(
        current: 9,
        best: 9,
        lastCheckIn: DateTime(2026, 7, 20),
      );
      final s1 = s0.record(DateTime(2026, 8, 2));
      expect(s1.current, 1);
      expect(s1.best, 9);
    });

    test('current exceeding best raises best', () {
      final s0 = StreakState(
        current: 7,
        best: 7,
        lastCheckIn: DateTime(2026, 8, 1),
      );
      expect(s0.record(DateTime(2026, 8, 2)).best, 8);
    });

    test('DST spring-forward day still counts as consecutive', () {
      // US spring-forward is 02:00 on 2026-03-08, so the 23-hour local
      // calendar day is Mar 8 -> Mar 9. A local-time diff truncates that to
      // 0 days and would break the streak; UTC-normalized dates must not.
      final s0 = StreakState(
        current: 3,
        best: 3,
        lastCheckIn: DateTime(2026, 3, 8),
      );
      final s1 = s0.record(DateTime(2026, 3, 9));
      expect(s1.current, 4);

      // Fall-back 2026-11-01 gives a 25-hour local day (Nov 1 -> Nov 2),
      // which must also count as exactly one day, not two.
      final f0 = StreakState(
        current: 2,
        best: 2,
        lastCheckIn: DateTime(2026, 11, 1),
      );
      expect(f0.record(DateTime(2026, 11, 2)).current, 3);
    });

    test('history keeps the NEWEST 30 days', () {
      var s = const StreakState();
      for (var i = 0; i < 40; i++) {
        s = s.record(DateTime(2026, 1, 1 + i)); // Dart normalizes overflow
      }
      expect(s.history.length, 30);
      expect(s.history.last, DateTime(2026, 2, 9)); // day 40
      expect(s.history.first, DateTime(2026, 1, 11)); // day 11 (oldest kept)
      expect(s.current, 40);
      expect(s.best, 40);
    });

    test('currentAt decays a lapsed run to 0 without touching stored state',
        () {
      final s = StreakState(
        current: 5,
        best: 5,
        lastCheckIn: DateTime(2026, 8, 1),
        history: [DateTime(2026, 8, 1)],
      );
      // Live today and yesterday...
      expect(s.currentAt(DateTime(2026, 8, 1, 20)), 5);
      expect(s.currentAt(DateTime(2026, 8, 2, 9)), 5);
      // ...lapsed from the day after that: the card must not advertise a run
      // that a check-in would collapse to 1.
      expect(s.currentAt(DateTime(2026, 8, 3)), 0);
      expect(s.currentAt(DateTime(2026, 9, 1)), 0);
      // Stored state is untouched (best/history survive for the record).
      expect(s.current, 5);
      // Clock skew backwards must not erase a real run.
      expect(s.currentAt(DateTime(2026, 7, 30)), 5);
    });

    test('checkedInOn is true only once the day is recorded', () {
      const empty = StreakState();
      expect(empty.checkedInOn(DateTime(2026, 8, 2)), isFalse);
      final s = empty.record(DateTime(2026, 8, 2, 7));
      expect(s.checkedInOn(DateTime(2026, 8, 2, 23)), isTrue);
      expect(s.checkedInOn(DateTime(2026, 8, 3)), isFalse);
      // Clock ahead: the day is already covered, so no dead button state.
      expect(s.checkedInOn(DateTime(2026, 8, 1)), isTrue);
    });

    test('post-reset rollback cannot duplicate or disorder history', () {
      final s = const StreakState()
          .record(DateTime(2026, 8, 1))
          .record(DateTime(2026, 8, 2));
      // reset() clears lastCheckIn, which disables the rollback guard.
      final afterReset =
          StreakState(current: 0, best: s.best, history: s.history);
      final rolled = afterReset.record(DateTime(2026, 8, 1));
      expect(rolled.history, [DateTime(2026, 8, 1), DateTime(2026, 8, 2)]);
      final again = rolled.record(DateTime(2026, 8, 2));
      expect(again.history, [DateTime(2026, 8, 1), DateTime(2026, 8, 2)]);
    });

    test('checkedIn reflects history by calendar date', () {
      final s = const StreakState()
          .record(DateTime(2026, 8, 1))
          .record(DateTime(2026, 8, 2));
      expect(s.checkedIn(DateTime(2026, 8, 1, 23, 59)), isTrue);
      expect(s.checkedIn(DateTime(2026, 8, 2)), isTrue);
      expect(s.checkedIn(DateTime(2026, 7, 31)), isFalse);
    });
  });

  group('StreakState serialization', () {
    test('round-trips through toJson/fromJson', () {
      final s = const StreakState()
          .record(DateTime(2026, 8, 1))
          .record(DateTime(2026, 8, 2));
      final r = StreakState.fromJson(s.toJson());
      expect(r.current, 2);
      expect(r.best, 2);
      expect(r.lastCheckIn, DateTime(2026, 8, 2));
      expect(r.history, [DateTime(2026, 8, 1), DateTime(2026, 8, 2)]);
    });

    test('tolerates missing fields and wrong types', () {
      final empty = StreakState.fromJson(const {});
      expect(empty.current, 0);
      expect(empty.best, 0);
      expect(empty.lastCheckIn, isNull);
      expect(empty.history, isEmpty);

      final bad = StreakState.fromJson(const {
        'current': 'nope',
        'best': -3,
        'last': 'not-a-date',
        'history': ['2026-08-01', 42, 'junk'],
      });
      expect(bad.current, 0);
      expect(bad.best, 0);
      expect(bad.lastCheckIn, isNull);
      expect(bad.history, [DateTime(2026, 8, 1)]);
    });
  });

  group('StreakNotifier', () {
    test('recordCheckIn persists across a fresh container', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final c1 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      final n1 = c1.read(streakProvider.notifier);
      await n1.recordCheckIn(now: DateTime(2026, 8, 1));
      await n1.recordCheckIn(now: DateTime(2026, 8, 2));
      expect(n1.state.current, 2);
      c1.dispose();

      final c2 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c2.dispose);
      final n2 = c2.read(streakProvider.notifier);
      expect(n2.state.current, 2);
      expect(n2.state.best, 2);
      expect(n2.state.lastCheckIn, DateTime(2026, 8, 2));
    });

    test('reset zeroes current, keeps best and history, allows same-day '
        'restart', () async {
      final c = await _container();
      final n = c.read(streakProvider.notifier);
      await n.recordCheckIn(now: DateTime(2026, 8, 1));
      await n.recordCheckIn(now: DateTime(2026, 8, 2));
      expect(n.state.current, 2);

      await n.reset();
      expect(n.state.current, 0);
      expect(n.state.best, 2);
      expect(n.state.history.length, 2); // past check-ins are facts

      // Showing up again the same day starts the new run immediately.
      await n.recordCheckIn(now: DateTime(2026, 8, 2));
      expect(n.state.current, 1);
      expect(n.state.best, 2);
      expect(n.state.history.length, 2); // no duplicate for the same day
    });
  });

  group('cross-feature check-in triggers', () {
    test('FR1 logRelapse resets the current streak, keeps best', () async {
      final c = await _container();
      final streak = c.read(streakProvider.notifier);
      await streak.recordCheckIn(now: DateTime(2026, 8, 1));
      await streak.recordCheckIn(now: DateTime(2026, 8, 2));
      expect(streak.state.current, 2);

      final sobriety = c.read(sobrietyProvider.notifier);
      sobriety.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      await sobriety.logRelapse(note: 'slip');

      expect(streak.state.current, 0);
      expect(streak.state.best, 2);
      expect(streak.state.history.length, 2);
    });

    test("saving tonight's inventory records today's check-in; a past-day "
        'edit does not', () async {
      final c = await _container();
      final inv = c.read(inventoryProvider.notifier);
      await inv.save(const InventoryEntry(
        dateIso: '2001-01-01',
        answers: {},
        notes: {},
        reflection: '',
        gratitude: [],
      ));
      expect(c.read(streakProvider).current, 0);

      await inv.save(InventoryEntry(
        dateIso: dateIsoOf(DateTime.now()),
        answers: const {},
        notes: const {},
        reflection: '',
        gratitude: const [],
      ));
      expect(c.read(streakProvider).current, 1);
    });

    test("saving today's mood entry records the check-in; a past-day entry "
        'does not', () async {
      final c = await _container();
      final mood = c.read(moodProvider.notifier);
      await mood.upsert(MoodEntry(dateIso: '2001-01-01', mood: 3));
      expect(c.read(streakProvider).current, 0);

      await mood.upsert(
        MoodEntry(dateIso: dateIsoOf(DateTime.now()), mood: 4),
      );
      expect(c.read(streakProvider).current, 1);
    });

    test('completing a meditation session records the check-in', () async {
      final c = await _container(tts: _FakeMedTts());
      final p = c.read(meditationPlayerProvider.notifier);
      const short = MeditationSession(
        id: 'x',
        title: 'X',
        description: 'Y',
        steps: [MedStep('Inhale', 2)],
      );
      p.load(short);
      p.start();
      p.tick();
      p.tick(); // completes
      expect(p.state.completed, isTrue);
      // _recordCompletion is async fire-and-forget; let it settle.
      await Future<void>.delayed(Duration.zero);
      expect(c.read(streakProvider).current, 1);
      p.pause(); // cancel the periodic timer before the test ends
    });
  });
}
