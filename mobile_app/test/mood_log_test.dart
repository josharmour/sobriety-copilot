// Tests for the FR4 mood check-in log: MoodEntry serialization (Task 1) and
// MoodNotifier upsert/query/persistence (Task 2).
//
// Follows the cross-cutting rule: notifiers are exercised through a
// ProviderContainer with a sharedPreferencesProvider override — never
// instantiated directly.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/daily/inventory.dart'
    show dateIsoOf;
import 'package:sobriety_copilot_mobile/features/daily/mood_log.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

Future<MoodNotifier> _notifier() async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
  );
  addTearDown(container.dispose);
  return container.read(moodProvider.notifier);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('MoodEntry serialization', () {
    test('mood entry round-trips and is keyed by date', () {
      final e = MoodEntry(
        dateIso: dateIsoOf(DateTime(2026, 8, 1)),
        mood: 4,
        label: 'Grateful',
        journal: 'Good meeting today.',
      );
      final r = MoodEntry.fromJson(e.toJson());
      expect(r.dateIso, '2026-08-01');
      expect(r.mood, 4);
      expect(r.label, 'Grateful');
      expect(r.journal, 'Good meeting today.');
    });

    test('fromJson clamps out-of-range mood and defaults missing fields', () {
      final e = MoodEntry.fromJson(const {'date': '2026-08-01', 'mood': 99});
      expect(e.mood, 5);
      expect(e.label, '');
      expect(e.journal, '');
      final low = MoodEntry.fromJson(const {'date': '2026-08-01', 'mood': -3});
      expect(low.mood, 1);
    });

    test('emotion map has the 13 labels with values in 1..5', () {
      expect(kMoodEmotions.length, 13);
      expect(kEmotionMood.keys.toSet(), kMoodEmotions.toSet());
      for (final v in kEmotionMood.values) {
        expect(v, inInclusiveRange(1, 5));
      }
    });

    test('toShareText renders label, date, mood scale, and journal', () {
      final e = MoodEntry(
        dateIso: '2026-08-01',
        mood: 5,
        label: 'Grateful',
        journal: '  Good meeting.  ',
      );
      final text = e.toShareText();
      expect(text, contains('Grateful — 2026-08-01'));
      expect(text, contains('Mood 5/5'));
      expect(text, contains('Good meeting.'));
    });
  });

  group('MoodNotifier upsert + entryFor', () {
    test('upsert replaces same-day entry and entryFor returns it', () async {
      final n = await _notifier();
      await n.upsert(
        MoodEntry(dateIso: '2026-08-01', mood: 3, label: 'Meh'),
      );
      await n.upsert(
        MoodEntry(dateIso: '2026-08-01', mood: 5, label: 'Great'),
      );
      expect(n.state.length, 1);
      expect(n.entryFor(DateTime(2026, 8, 1))!.mood, 5);
      expect(n.entryFor(DateTime(2026, 8, 2)), isNull);
    });

    test('entryFor compares calendar dates only, never raw DateTime', () async {
      final n = await _notifier();
      await n.upsert(MoodEntry(dateIso: '2026-08-01', mood: 4));
      // Same calendar day at a different wall-clock time must still match.
      final e = n.entryFor(DateTime(2026, 8, 1, 23, 59, 59));
      expect(e, isNotNull);
      expect(e!.mood, 4);
    });

    test('list stays sorted newest-first on upsert', () async {
      final n = await _notifier();
      await n.upsert(MoodEntry(dateIso: '2026-07-01', mood: 2));
      await n.upsert(MoodEntry(dateIso: '2026-08-01', mood: 5));
      await n.upsert(MoodEntry(dateIso: '2026-08-10', mood: 3));
      expect(n.state.map((e) => e.dateIso).toList(),
          ['2026-08-10', '2026-08-01', '2026-07-01']);
    });

    test('entries persist across a fresh container (same prefs)', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();

      final c1 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      await c1.read(moodProvider.notifier).upsert(
            MoodEntry(dateIso: '2026-08-01', mood: 4, journal: 'hello'),
          );
      c1.dispose();

      final c2 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c2.dispose);
      final e = c2.read(moodProvider.notifier).entryFor(DateTime(2026, 8, 1));
      expect(e, isNotNull);
      expect(e!.journal, 'hello');
    });

    test('drops entries older than two years on upsert', () async {
      final n = await _notifier();
      final old = DateTime.now().subtract(const Duration(days: 800));
      await n.upsert(MoodEntry(dateIso: dateIsoOf(old), mood: 1));
      await n.upsert(MoodEntry(dateIso: dateIsoOf(DateTime.now()), mood: 4));
      expect(n.state.any((e) => e.dateIso == dateIsoOf(old)), isFalse);
      expect(n.state.length, 1);
    });
  });

  group('MoodNotifier delete', () {
    test('delete removes the entry and the journal text leaves the disk',
        () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final c1 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      final n1 = c1.read(moodProvider.notifier);
      await n1.upsert(
        MoodEntry(dateIso: '2026-08-01', mood: 2, journal: 'rough day'),
      );
      await n1.upsert(MoodEntry(dateIso: '2026-08-02', mood: 4));
      await n1.delete(DateTime(2026, 8, 1));
      expect(n1.state.map((e) => e.dateIso).toList(), ['2026-08-02']);
      c1.dispose();

      // The removal survives a reload and the text is gone from storage.
      final c2 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c2.dispose);
      expect(
        c2.read(moodProvider.notifier).entryFor(DateTime(2026, 8, 1)),
        isNull,
      );
      expect(prefs.getString(MoodNotifier.prefsKey), isNot(contains('rough')));
    });

    test('delete of a day with no entry is a no-op', () async {
      final n = await _notifier();
      await n.upsert(MoodEntry(dateIso: '2026-08-01', mood: 3));
      await n.delete(DateTime(2026, 7, 15));
      expect(n.state.length, 1);
      expect(n.entryFor(DateTime(2026, 8, 1)), isNotNull);
    });
  });
}
