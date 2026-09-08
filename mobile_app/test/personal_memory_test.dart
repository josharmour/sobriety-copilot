// Tests for FR11 Task 1: PersonalMemory model + notifier + persistence.
//
// Covers: MemoryFact / MemoryThread / PersonalProfile JSON round-trips,
// PersonalMemory immutable with* operations (fact dedupe by normalized
// token-set Jaccard >= 0.9, 100-fact FIFO cap, 12-thread LRU cap, thread
// upsert/unresolve), and PersonalMemoryNotifier load/persist/reload
// behavior through a ProviderContainer with a sharedPreferencesProvider
// override (cross-cutting rule — never instantiate the notifier directly).

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Fresh mock prefs + container wired per the FR notifier-test pattern.
Future<ProviderContainer> _container() async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
  );
  addTearDown(container.dispose);
  return container;
}

/// Prefs primed with [initial] stored under the memory key.
Future<SharedPreferences> _primedPrefs(String initial) async {
  SharedPreferences.setMockInitialValues(<String, Object>{
    PersonalMemoryNotifier.prefsKey: initial,
  });
  return SharedPreferences.getInstance();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('MemoryFact serialization', () {
    test('round-trips every field', () {
      final f = MemoryFact(
        id: 'fact_1725661800000000_1',
        text: 'Talks about missing his old driving route past the bar',
        createdAt: DateTime(2026, 9, 7, 10, 30, 0),
        sourceConversationId: 'conv-2026-09-07-abc',
      );
      final r = MemoryFact.fromJson(f.toJson());
      expect(r.id, f.id);
      expect(r.text, f.text);
      expect(r.createdAt.toIso8601String(), f.createdAt.toIso8601String());
      expect(r.sourceConversationId, f.sourceConversationId);
      expect(r.toJson(), f.toJson());
    });

    test('fromJson defaults missing keys tolerantly', () {
      final f = MemoryFact.fromJson(const <String, dynamic>{});
      expect(f.id, '');
      expect(f.text, '');
      expect(f.sourceConversationId, '');
      expect(f.createdAt, DateTime.fromMillisecondsSinceEpoch(0));
    });
  });

  group('MemoryThread serialization', () {
    test('round-trips every field', () {
      final t = MemoryThread(
        id: 'step-8-amends',
        title: 'Step 8 amends list',
        lastDetail: 'Working out who to write to.',
        updatedAt: DateTime(2026, 9, 7, 9, 0, 0, 123),
        resolved: true,
      );
      final r = MemoryThread.fromJson(t.toJson());
      expect(r.id, t.id);
      expect(r.title, t.title);
      expect(r.lastDetail, t.lastDetail);
      expect(r.updatedAt.toIso8601String(), t.updatedAt.toIso8601String());
      expect(r.resolved, isTrue);
      expect(r.toJson(), t.toJson());
    });

    test('resolved defaults to false and missing keys default', () {
      final t = MemoryThread.fromJson(const <String, dynamic>{});
      expect(t.id, '');
      expect(t.title, '');
      expect(t.lastDetail, '');
      expect(t.resolved, isFalse);
      final r = MemoryThread.fromJson(const {'id': 'x'});
      expect(r.resolved, isFalse);
    });
  });

  group('PersonalProfile serialization', () {
    test('round-trips sponsor, homeGroup, goal, triggers', () {
      final p = PersonalProfile(
        sponsor: 'Mike',
        homeGroup: 'Sunrise Group',
        goal: '90 meetings in 90 days',
        triggers: const ['Friday after work', 'Old bar route'],
      );
      final r = PersonalProfile.fromJson(p.toJson());
      expect(r.sponsor, 'Mike');
      expect(r.homeGroup, 'Sunrise Group');
      expect(r.goal, '90 meetings in 90 days');
      expect(r.triggers, ['Friday after work', 'Old bar route']);
      expect(r.toJson(), p.toJson());
    });

    test('fromJson is tolerant of missing keys', () {
      final p = PersonalProfile.fromJson(const <String, dynamic>{});
      expect(p.sponsor, isNull);
      expect(p.homeGroup, isNull);
      expect(p.goal, isNull);
      expect(p.triggers, isEmpty);
    });
  });

  group('PersonalMemory aggregate round-trip', () {
    test('profile + facts + threads survive toJson/fromJson', () {
      var m = const PersonalMemory();
      m = m.withProfile(sponsor: 'Mike', goal: 'Stay sober today');
      m = m.withFactAdded(
        'Prefers morning meetings',
        sourceConversationId: 'conv-1',
      );
      m = m.withThreadUpdated('step-4', 'Step 4 inventory', 'Moral inventory');
      final r = PersonalMemory.fromJson(m.toJson());
      expect(r.profile.sponsor, 'Mike');
      expect(r.profile.goal, 'Stay sober today');
      expect(r.facts.length, 1);
      expect(r.facts.single.text, 'Prefers morning meetings');
      expect(r.threads.length, 1);
      expect(r.threads.single.title, 'Step 4 inventory');
      expect(r.toJson(), m.toJson());
    });

    test('facts and threads are immutable on the aggregate', () {
      final m = const PersonalMemory();
      expect(m.profile.sponsor, isNull);
      expect(m.facts, isEmpty);
      expect(m.threads, isEmpty);
      expect(m.toJson()['facts'], isEmpty);
    });
  });

  group('withFactAdded: trimming, capping, dedupe', () {
    test('trims whitespace and stores the source conversation', () {
      final m = const PersonalMemory().withFactAdded(
        '  Caffeine free for a month  ',
        sourceConversationId: 'conv-7',
      );
      expect(m.facts.single.text, 'Caffeine free for a month');
      expect(m.facts.single.sourceConversationId, 'conv-7');
      expect(m.facts.single.id, isNotEmpty);
    });

    test('caps fact text at 120 characters', () {
      final long = 'x' * 200;
      final m = const PersonalMemory().withFactAdded(
        long,
        sourceConversationId: 'conv-1',
      );
      expect(m.facts.single.text.length, 120);
    });

    test('blank text is not added', () {
      final m = const PersonalMemory().withFactAdded(
        '   ',
        sourceConversationId: 'conv-1',
      );
      expect(m.facts, isEmpty);
    });

    test(
      'duplicate (case + punctuation variant) returns the same instance',
      () {
        var m = const PersonalMemory();
        m = m.withFactAdded(
          'Talks about missing his old driving route past the bar',
          sourceConversationId: 'conv-1',
        );
        final before = m;
        final after = m.withFactAdded(
          'talks about missing his OLD driving route past the BAR!!',
          sourceConversationId: 'conv-2',
        );
        expect(identical(after, before), isTrue);
        expect(after.facts.length, 1);
        expect(after.facts.single.sourceConversationId, 'conv-1');
      },
    );

    test('duplicate with words reordered is rejected', () {
      var m = const PersonalMemory();
      m = m.withFactAdded(
        'missing his old driving route past the bar talks about',
        sourceConversationId: 'conv-1',
      );
      final after = m.withFactAdded(
        'Talks about missing his old driving route past the bar',
        sourceConversationId: 'conv-2',
      );
      expect(identical(after, m), isTrue);
      expect(after.facts.length, 1);
    });

    test('a genuinely different fact below 0.9 similarity is added', () {
      var m = const PersonalMemory();
      m = m.withFactAdded(
        'Meeting with sponsor at seven tomorrow',
        sourceConversationId: 'conv-1',
      );
      final after = m.withFactAdded(
        'Meeting with sponsor at seven today',
        sourceConversationId: 'conv-2',
      );
      expect(after.facts.length, 2);
    });

    test('near-duplicate at exactly the 0.9 boundary is rejected', () {
      const base =
          'one two three four five six seven eight nine ten eleven twelve '
          'thirteen fourteen fifteen sixteen seventeen eighteen apples';
      // 19 tokens, one swapped -> 18 shared / 20 union = 0.9 exactly.
      const variant =
          'one two three four five six seven eight nine ten eleven twelve '
          'thirteen fourteen fifteen sixteen seventeen eighteen bananas';
      var m = const PersonalMemory();
      m = m.withFactAdded(base, sourceConversationId: 'conv-1');
      final after = m.withFactAdded(variant, sourceConversationId: 'conv-2');
      expect(after.facts.length, 1);
    });
  });

  group('Caps', () {
    test('101 facts -> 100 with the oldest dropped', () {
      var m = const PersonalMemory();
      for (var i = 0; i < 101; i++) {
        m = m.withFactAdded('fact number $i', sourceConversationId: 'conv-$i');
      }
      expect(m.facts.length, 100);
      expect(m.facts.any((f) => f.text == 'fact number 0'), isFalse);
      expect(m.facts.last.text, 'fact number 100');
      expect(m.facts.first.text, 'fact number 1');
    });

    test('13 threads -> 12 with the least recently updated dropped', () {
      var m = const PersonalMemory();
      for (var i = 0; i < 13; i++) {
        m = m.withThreadUpdated('thread-$i', 'Thread $i', 'detail $i');
      }
      expect(m.threads.length, 12);
      expect(m.threads.any((t) => t.id == 'thread-0'), isFalse);
      expect(m.threads.any((t) => t.id == 'thread-12'), isTrue);
    });

    test('overflow drops the LRU even when the newest was touched mid-way', () {
      var m = const PersonalMemory();
      for (var i = 0; i < 13; i++) {
        m = m.withThreadUpdated('thread-$i', 'Thread $i', 'detail $i');
      }
      // 12 remain (thread-1..thread-12). Touch thread-1 to make it newest,
      // then add a 13th: the LRU (thread-2) must go, not thread-1.
      m = m.withThreadUpdated('thread-1', 'Thread 1', 'updated detail');
      m = m.withThreadUpdated('thread-13', 'Thread 13', 'detail 13');
      expect(m.threads.length, 12);
      expect(m.threads.any((t) => t.id == 'thread-2'), isFalse);
      expect(m.threads.any((t) => t.id == 'thread-1'), isTrue);
      expect(m.threads.any((t) => t.id == 'thread-13'), isTrue);
    });
  });

  group('withThreadUpdated semantics', () {
    test('upserts a new thread and caps title and detail lengths', () {
      var m = const PersonalMemory();
      m = m.withThreadUpdated(
        'step-8-amends',
        'A title that is far, far longer than the fifty character budget here',
        'A detail that is also deliberately way too long and keeps going and '
            'going past the one hundred and twenty character budget that a '
            'short next-step note should never exceed in practice',
      );
      expect(m.threads.single.id, 'step-8-amends');
      expect(m.threads.single.title.length, lessThanOrEqualTo(50));
      expect(m.threads.single.lastDetail.length, lessThanOrEqualTo(120));
      expect(m.threads.single.resolved, isFalse);
    });

    test('updates an existing thread in place and unresolves it', () {
      var m = const PersonalMemory();
      m = m.withThreadUpdated('step-8', 'Step 8 amends', 'listing people');
      m = m.withThreadResolved('step-8');
      expect(m.threads.single.resolved, isTrue);

      final bumped = m.threads.single.updatedAt;
      m = m.withThreadUpdated(
        'step-8',
        'Step 8 amends list',
        'who to write to',
      );
      expect(m.threads.length, 1);
      expect(m.threads.single.id, 'step-8');
      expect(m.threads.single.title, 'Step 8 amends list');
      expect(m.threads.single.lastDetail, 'who to write to');
      expect(m.threads.single.resolved, isFalse);
      expect(
        m.threads.single.updatedAt.isAfter(bumped),
        isTrue,
        reason: 'updating must bump updatedAt',
      );
    });

    test(
      'empty title keeps the old title; empty detail keeps the old detail',
      () {
        var m = const PersonalMemory();
        m = m.withThreadUpdated('step-8', 'Step 8 amends', 'listing people');
        m = m.withThreadUpdated('step-8', '   ', '');
        expect(m.threads.single.title, 'Step 8 amends');
        expect(m.threads.single.lastDetail, 'listing people');
      },
    );

    test('new thread with a null detail starts with an empty lastDetail', () {
      final m = const PersonalMemory().withThreadUpdated(
        'new-topic',
        'New topic',
        null,
      );
      expect(m.threads.single.lastDetail, '');
    });
  });

  group('withProfile / removals / clear', () {
    test('withProfile copy-with keeps fields that are not provided', () {
      var m = const PersonalMemory();
      m = m.withProfile(sponsor: 'Mike', homeGroup: 'Sunrise');
      final m2 = m.withProfile(goal: '90 in 90');
      expect(m2.profile.sponsor, 'Mike');
      expect(m2.profile.homeGroup, 'Sunrise');
      expect(m2.profile.goal, '90 in 90');
      expect(m2.profile.triggers, isEmpty);
      // Original untouched (immutability).
      expect(m.profile.goal, isNull);
    });

    test('withProfile replaces triggers wholesale when provided', () {
      var m = const PersonalMemory();
      m = m.withProfile(triggers: const ['old bar route']);
      final m2 = m.withProfile(triggers: const ['Friday night']);
      expect(m2.profile.triggers, ['Friday night']);
      expect(m.profile.triggers, ['old bar route']);
    });

    test('withFactRemoved and withThreadRemoved delete by id', () {
      var m = const PersonalMemory();
      m = m.withFactAdded('first fact', sourceConversationId: 'c1');
      m = m.withFactAdded('second fact', sourceConversationId: 'c2');
      m = m.withThreadUpdated('t1', 'Thread one', 'd1');
      m = m.withThreadUpdated('t2', 'Thread two', 'd2');
      final id = m.facts.first.id;
      m = m.withFactRemoved(id);
      m = m.withThreadRemoved('t1');
      expect(m.facts.length, 1);
      expect(m.facts.single.text, 'second fact');
      expect(m.threads.length, 1);
      expect(m.threads.single.id, 't2');
    });

    test('removing an unknown id returns the same instance', () {
      final m = const PersonalMemory().withFactAdded(
        'a fact',
        sourceConversationId: 'c1',
      );
      final a = m.withFactRemoved('nope');
      final b = m.withThreadRemoved('nope');
      expect(identical(a, m), isTrue);
      expect(identical(b, m), isTrue);
    });

    test('withAllCleared resets facts, threads, and profile', () {
      var m = const PersonalMemory();
      m = m.withProfile(sponsor: 'Mike', goal: 'Stay sober');
      m = m.withFactAdded('a fact', sourceConversationId: 'c1');
      m = m.withThreadUpdated('t1', 'Thread', 'detail');
      final cleared = m.withAllCleared();
      expect(cleared.facts, isEmpty);
      expect(cleared.threads, isEmpty);
      expect(cleared.profile.sponsor, isNull);
      expect(cleared.profile.goal, isNull);
    });
  });

  group('PersonalMemoryNotifier', () {
    test('addFact persists and a fresh container reloads the fact', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final c1 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      final n1 = c1.read(personalMemoryProvider.notifier);
      expect(n1.state.facts, isEmpty);
      await n1.addFact('Feels strong after 60 days', 'conv-1');
      expect(n1.state.facts.single.text, 'Feels strong after 60 days');
      c1.dispose();

      final c2 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c2.dispose);
      final n2 = c2.read(personalMemoryProvider.notifier);
      expect(n2.state.facts.single.text, 'Feels strong after 60 days');
      expect(n2.state.facts.single.sourceConversationId, 'conv-1');
    });

    test('profile + threads persist together as one JSON blob', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final c1 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      final n1 = c1.read(personalMemoryProvider.notifier);
      await n1.updateProfile(sponsor: 'Mike');
      await n1.upsertThread('step-8', 'Step 8 amends', 'listing people');
      await n1.addFact('a fact', 'conv-1');
      c1.dispose();

      final blob = prefs.getString(PersonalMemoryNotifier.prefsKey);
      expect(blob, isNotNull);
      final decoded = jsonDecode(blob!) as Map<String, dynamic>;
      expect(decoded['profile'], isA<Map<String, dynamic>>());
      expect(decoded['facts'], isA<List<dynamic>>());
      expect(decoded['threads'], isA<List<dynamic>>());

      final c2 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c2.dispose);
      final n2 = c2.read(personalMemoryProvider.notifier);
      expect(n2.state.profile.sponsor, 'Mike');
      expect(n2.state.threads.single.title, 'Step 8 amends');
      expect(n2.state.facts.length, 1);
    });

    test('notifier mutations route through with* semantics', () async {
      final c = await _container();
      final n = c.read(personalMemoryProvider.notifier);
      await n.addFact('A fact to remove', 'conv-1');
      final factId = n.state.facts.single.id;
      await n.upsertThread('t1', 'Thread one', 'detail');
      await n.resolveThread('t1');
      expect(n.state.threads.single.resolved, isTrue);
      await n.upsertThread('t1', 'Thread one updated', 'new detail');
      expect(n.state.threads.length, 1);
      expect(n.state.threads.single.title, 'Thread one updated');
      expect(n.state.threads.single.resolved, isFalse);
      await n.removeFact(factId);
      await n.removeThread('t1');
      expect(n.state.facts, isEmpty);
      expect(n.state.threads, isEmpty);
    });

    test('addFact duplicate does not grow state', () async {
      final c = await _container();
      final n = c.read(personalMemoryProvider.notifier);
      await n.addFact('Loves the sunrise meeting', 'conv-1');
      await n.addFact('loves the SUNRISE meeting!!!', 'conv-2');
      expect(n.state.facts.length, 1);
    });

    test('forgetAll empties state and persists an empty record', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final prefs = await SharedPreferences.getInstance();
      final c1 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      final n1 = c1.read(personalMemoryProvider.notifier);
      await n1.updateProfile(sponsor: 'Mike', goal: 'Stay sober');
      await n1.addFact('a fact', 'conv-1');
      await n1.upsertThread('t1', 'Thread', 'detail');
      await n1.forgetAll();
      expect(n1.state.facts, isEmpty);
      expect(n1.state.threads, isEmpty);
      expect(n1.state.profile.sponsor, isNull);
      c1.dispose();

      final blob = prefs.getString(PersonalMemoryNotifier.prefsKey);
      expect(blob, isNotNull, reason: 'forgetAll must persist the empty state');
      final decoded = jsonDecode(blob!) as Map<String, dynamic>;
      expect(decoded['facts'], isEmpty);
      expect(decoded['threads'], isEmpty);

      final c2 = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c2.dispose);
      final n2 = c2.read(personalMemoryProvider.notifier);
      expect(n2.state.facts, isEmpty);
      expect(n2.state.profile.sponsor, isNull);
    });

    test(
      'tolerant load: corrupted blob yields empty memory, no throw',
      () async {
        final prefs = await _primedPrefs('{not valid json!!');
        final c = ProviderContainer(
          overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
        );
        addTearDown(c.dispose);
        final n = c.read(personalMemoryProvider.notifier);
        expect(n.state.facts, isEmpty);
        expect(n.state.threads, isEmpty);
        expect(n.state.profile.sponsor, isNull);
        // Notifier is still fully usable after a corrupt load.
        await n.addFact('still works', 'conv-1');
        expect(n.state.facts.single.text, 'still works');
      },
    );

    test(
      'tolerant load: valid JSON of the wrong shape yields empty memory',
      () async {
        final prefs = await _primedPrefs('[1, 2, 3]');
        final c = ProviderContainer(
          overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
        );
        addTearDown(c.dispose);
        final n = c.read(personalMemoryProvider.notifier);
        expect(n.state.facts, isEmpty);
        expect(n.state.threads, isEmpty);
      },
    );

    test('load normalizes an over-cap stored record', () async {
      final bloated = {
        'profile': {'sponsor': 'Mike'},
        'facts': [
          for (var i = 0; i < 150; i++)
            {
              'id': 'f$i',
              'text': 'fact $i',
              'created_at': '2026-09-07T10:00:0${i % 10}.000',
              'source_conversation_id': 'conv-$i',
            },
        ],
        'threads': <Object>[],
      };
      final prefs = await _primedPrefs(jsonEncode(bloated));
      final c = ProviderContainer(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      );
      addTearDown(c.dispose);
      final n = c.read(personalMemoryProvider.notifier);
      expect(n.state.facts.length, 100);
      expect(n.state.profile.sponsor, 'Mike');
    });
  });
}
