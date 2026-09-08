// Tests for FR11 Task 4: the memory snapshot builder + thread resume prompt.
//
// Pure-module tests: MemorySnapshotInput is this module's own decoupled DTO
// (the chat_notifier agent maps PersonalMemory -> MemorySnapshotInput), so no
// Riverpod container / SharedPreferences override is needed here.

import 'package:flutter_test/flutter_test.dart';

import 'package:sobriety_copilot_mobile/features/personal_memory/memory_snapshot.dart';

const String _suffix =
    '(This is private memory from their device - use it if relevant, do not recite it verbatim.)';

ThreadRef _thread(
  String title, {
  String lastDetail = '',
  DateTime? updatedAt,
  bool resolved = false,
}) =>
    ThreadRef(
      title: title,
      lastDetail: lastDetail,
      updatedAt: updatedAt ?? DateTime(2026, 9, 1),
      resolved: resolved,
    );

void main() {
  group('buildClientContextSnapshot — empty input', () {
    test('returns empty string when nothing is present', () {
      expect(buildClientContextSnapshot(const MemorySnapshotInput()), '');
    });

    test('blank fields and resolved-only threads still render empty', () {
      final input = MemorySnapshotInput(
        triggers: const ['', '   '],
        goal: '   ',
        factTexts: const ['', '  '],
        threads: [
          _thread('A finished topic', updatedAt: DateTime(2026, 8, 30), resolved: true),
        ],
      );
      expect(buildClientContextSnapshot(input), '');
    });
  });

  group('buildClientContextSnapshot — suffix + full render', () {
    test('any content always carries the non-recitable suffix', () {
      final snap = buildClientContextSnapshot(
        const MemorySnapshotInput(triggers: ['evenings alone']),
      );
      expect(snap, endsWith(_suffix));
      expect(snap, contains('do not recite it verbatim'));
      expect(snap, contains('This is private memory from their device'));
    });

    test('renders every present section in priority order when under budget', () {
      final input = MemorySnapshotInput(
        triggers: const ['evenings alone', 'passing the old bar'],
        goal: 'Rebuild trust with my wife',
        factTexts: const [
          'Reads a daily reflection every morning',
          'Sponsor is Sue, ten years sober',
          'A third fact that must never render', // only the top 2 facts render
        ],
        threads: [
          _thread(
            'Step 8 amends',
            lastDetail: 'writing the list',
            updatedAt: DateTime(2026, 9, 1, 9),
          ),
        ],
      );
      final snap = buildClientContextSnapshot(input, maxChars: 2000);
      expect(
        snap,
        'Currently discussing: Step 8 amends — writing the list; '
        'Triggers: evenings alone, passing the old bar; '
        'Goal: Rebuild trust with my wife; '
        'Reads a daily reflection every morning; '
        'Sponsor is Sue, ten years sober '
        '$_suffix',
      );
      expect(snap, isNot(contains('A third fact')));
    });

    test('only the most recent unresolved thread is rendered', () {
      final input = MemorySnapshotInput(
        threads: [
          _thread(
            'Step 8 amends',
            lastDetail: 'writing the list',
            updatedAt: DateTime(2026, 8, 25),
          ),
          _thread(
            'Telling my family',
            lastDetail: 'drafting what to say',
            updatedAt: DateTime(2026, 9, 2),
          ),
          _thread(
            'An old resolved topic',
            lastDetail: 'done',
            updatedAt: DateTime(2026, 9, 3),
            resolved: true,
          ),
        ],
      );
      final snap = buildClientContextSnapshot(input, maxChars: 2000);
      expect(
        snap,
        startsWith('Currently discussing: Telling my family — drafting what to say'),
      );
      expect(snap, isNot(contains('Step 8 amends')));
      expect(snap, isNot(contains('An old resolved topic')));
    });
  });

  group('buildClientContextSnapshot — priority & cap enforcement', () {
    test('over budget: most recent unresolved thread beats facts (facts drop first)', () {
      final input = MemorySnapshotInput(
        triggers: const ['driving past the old bar on Route 9, Friday nights alone, feeling hungry and angry'],
        goal: 'stay sober through the holidays and make it to my 90-day chip on December 3rd',
        factTexts: [
          'Has been attending the Tuesday 7pm mens meeting at the downtown clubhouse and sits in '
              'the back row with Bill, who he met at his first meeting back in March. He has only '
              'missed one week since he started.',
          'Wants to make amends to his brother eventually but is not ready yet, so he is starting '
              'with easier relationships first. His sponsor keeps telling him to take it slowly and '
              'pray about it daily.',
        ],
        threads: [
          _thread(
            'Step 8 amends',
            lastDetail: 'writing the list',
            updatedAt: DateTime(2026, 8, 25),
          ),
          _thread(
            'Telling my family',
            lastDetail: 'drafting what to say to my wife about the relapse',
            updatedAt: DateTime(2026, 9, 2),
          ),
        ],
      );
      final snap = buildClientContextSnapshot(input); // maxChars 400
      expect(snap.length, lessThanOrEqualTo(400));
      expect(
        snap,
        startsWith(
          'Currently discussing: Telling my family — drafting what to say to my wife about the relapse',
        ),
      );
      expect(snap, isNot(contains('Step 8 amends'))); // older thread never renders
      expect(snap, contains('Triggers:'));
      expect(snap, contains('Goal:'));
      expect(snap, isNot(contains('mens meeting'))); // facts are lowest priority
      expect(snap, isNot(contains('amends to his brother')));
      expect(snap, endsWith(_suffix));
    });

    test('deeper cut: triggers drop before the thread, keeping the suffix', () {
      final longTriggers =
          'late-night urges after 10pm when the house is quiet, ' * 6;
      final input = MemorySnapshotInput(
        triggers: [longTriggers.trim()],
        threads: [
          _thread(
            'Step 8 amends',
            lastDetail: 'working out who to write to first',
            updatedAt: DateTime(2026, 9, 1),
          ),
        ],
      );
      final snap = buildClientContextSnapshot(input);
      expect(snap.length, lessThanOrEqualTo(400));
      expect(snap, startsWith('Currently discussing: Step 8 amends'));
      expect(snap, isNot(contains('Triggers:')));
      expect(snap, endsWith(_suffix));
    });

    test('~700-char full render is capped at 400 with the suffix intact', () {
      final input = MemorySnapshotInput(
        triggers: const ['driving past the old bar on Route 9, Friday nights alone, feeling hungry and angry'],
        goal: 'stay sober through the holidays and make it to my 90-day chip on December 3rd',
        factTexts: [
          'Has been attending the Tuesday 7pm mens meeting at the downtown clubhouse and sits in '
              'the back row with Bill, who he met at his first meeting back in March. He has only '
              'missed one week since he started.',
          'Wants to make amends to his brother eventually but is not ready yet, so he is starting '
              'with easier relationships first. His sponsor keeps telling him to take it slowly and '
              'pray about it daily.',
        ],
        threads: [
          _thread(
            'Telling my family',
            lastDetail: 'drafting what to say to my wife about the relapse',
            updatedAt: DateTime(2026, 9, 2),
          ),
        ],
      );
      // Sanity: the uncapped render really is ~700 chars so the cap is exercised.
      final uncapped = buildClientContextSnapshot(input, maxChars: 9999);
      expect(uncapped.length, greaterThanOrEqualTo(700));

      final snap = buildClientContextSnapshot(input);
      expect(snap.length, lessThanOrEqualTo(400));
      expect(snap.length, greaterThanOrEqualTo(350)); // still meaningful content
      expect(snap, contains('do not recite it verbatim'));
      expect(snap, startsWith('Currently discussing: Telling my family'));
      expect(snap, isNot(contains('mens meeting')));
      expect(snap, endsWith(_suffix));
    });

    test('single oversized item is truncated with ellipsis so the suffix still fits', () {
      final hugeFact =
          'remembers to pray every single morning before getting out of bed and keeps a gratitude '
          'list on his nightstand next to the big book that his grandfather gave him when he first '
          'got sober back in 1998 and which he still reads from almost every night before falling '
          'asleep no matter how tired he is after a long shift at the warehouse. ' * 2;
      final snap = buildClientContextSnapshot(
        MemorySnapshotInput(factTexts: [hugeFact]),
      );
      expect(snap.length, lessThanOrEqualTo(400));
      expect(snap, endsWith(_suffix));
      expect(snap, contains('...'));
      expect(snap, isNot(contains(hugeFact)));
      expect(snap, startsWith(hugeFact.substring(0, 40)));
    });

    test('an oversized thread detail is shed before the title is truncated', () {
      final input = MemorySnapshotInput(
        threads: [
          _thread(
            'Sponsor chat',
            lastDetail: 'planning what to say about the amends ' * 20,
            updatedAt: DateTime(2026, 9, 1),
          ),
        ],
      );
      final snap = buildClientContextSnapshot(input);
      expect(snap.length, lessThanOrEqualTo(400));
      expect(snap, startsWith('Currently discussing: Sponsor chat'));
      expect(snap, isNot(contains(' — '))); // detail dropped, not truncated title
      expect(snap, endsWith(_suffix));
    });
  });

  group('resumePromptFor', () {
    test('sentence-cases the title and keeps the em-dash detail', () {
      final t = _thread(
        'STEP 8 AMENDS',
        lastDetail: 'listing who to write to',
        updatedAt: DateTime(2026, 9, 1),
      );
      expect(
        resumePromptFor(t),
        'Pick up where we left off: we were talking about Step 8 amends — '
        'listing who to write to Can you help me keep going?',
      );
    });

    test('mixed-case title is lowercased except the first letter', () {
      final t = _thread(
        'GoIng To A MeEting TONIGHT',
        lastDetail: 'finding a ride',
        updatedAt: DateTime(2026, 9, 1),
      );
      final prompt = resumePromptFor(t);
      expect(prompt, contains('we were talking about Going to a meeting tonight —'));
      expect(prompt, isNot(contains('GoIng')));
      expect(prompt, isNot(contains('TONIGHT')));
    });

    test('no detail: the em-dash clause is dropped entirely', () {
      final t = _thread('Telling my family', updatedAt: DateTime(2026, 9, 1));
      expect(
        resumePromptFor(t),
        'Pick up where we left off: we were talking about Telling my family '
        'Can you help me keep going?',
      );
      expect(resumePromptFor(t), isNot(contains('—')));
    });

    test('whitespace-only detail is treated as absent', () {
      final t = _thread(
        'Step 8 amends',
        lastDetail: '   ',
        updatedAt: DateTime(2026, 9, 1),
      );
      expect(resumePromptFor(t), isNot(contains('—')));
      expect(resumePromptFor(t), contains('about Step 8 amends Can you'));
    });
  });

  group('hasAnythingToInject', () {
    test('all-empty input is false', () {
      expect(hasAnythingToInject(const MemorySnapshotInput()), isFalse);
    });

    test('resolved-thread-only input is false', () {
      expect(
        hasAnythingToInject(
          MemorySnapshotInput(
            threads: [
              _thread('Done topic', updatedAt: DateTime(2026, 8, 1), resolved: true),
            ],
          ),
        ),
        isFalse,
      );
    });

    test('an unresolved thread alone is true', () {
      expect(
        hasAnythingToInject(
          MemorySnapshotInput(
            threads: [_thread('Step 8 amends', updatedAt: DateTime(2026, 9, 1))],
          ),
        ),
        isTrue,
      );
    });

    test('each populated field alone is true', () {
      expect(
        hasAnythingToInject(
          const MemorySnapshotInput(triggers: ['late nights']),
        ),
        isTrue,
      );
      expect(
        hasAnythingToInject(const MemorySnapshotInput(goal: 'stay sober')),
        isTrue,
      );
      expect(
        hasAnythingToInject(const MemorySnapshotInput(factTexts: ['a fact'])),
        isTrue,
      );
    });
  });
}
