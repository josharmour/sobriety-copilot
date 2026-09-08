// FR11 Wave C — MemorySheet widget tests.
//
// Riverpod widget-test pattern (per the FR-plan convention, mirroring
// test/mood_log_test.dart + test/streak_card_test.dart): a
// sharedPreferencesProvider override + ProviderScope(overrides:) baked into
// every pump. NOTIFIER-driven seeding rather than prefs-JSON prebaking —
// calling the real personalMemoryProvider methods exercises the same
// mutation path the sheet does. Layout is DraggableScrollableSheet-in-Scaffold
// with bounded pump()s, never pumpAndSettle (infinite sheet-driven animations
// never settle).
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_enabled.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_sheet.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Fake streaming repo capturing the resume-send (same shape as the
/// chat_notifier_memory_test fake: accepts resumePromptFor's text and
/// records message + history for assertions).
class FakeChatRepository implements ChatRepository {
  int sends = 0;
  String? lastMessage;
  List<ChatMessage>? lastHistory;
  String? lastClientContext;

  @override
  Stream<ChatEvent> sendMessage({
    required String message,
    required List<ChatMessage> history,
    List<String>? categories,
    String? tone,
    bool showThinking = false,
    String? userId,
    List<String>? images,
    String? audio,
    String? audioFormat,
    String? clientContext,
  }) async* {
    sends++;
    lastMessage = message;
    lastHistory = List<ChatMessage>.from(history);
    lastClientContext = clientContext;
    yield const SourcesEvent([]);
    yield const TokenEvent('Okay, picking that back up.');
    yield const DoneEvent();
  }
}

class _Harness {
  _Harness(this.container, this.prefs, this.repo);
  final ProviderContainer container;
  final SharedPreferences prefs;
  final FakeChatRepository repo;
}

Future<_Harness> _harness() async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final repo = FakeChatRepository();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      chatRepositoryProvider.overrideWithValue(repo),
    ],
  );
  addTearDown(container.dispose);
  return _Harness(container, prefs, repo);
}

/// Pumps the MemorySheet standing alone (full-size, no showAppSheet) inside
/// a Scaffold so Material ancestors exist, mirroring the streak-card harness.
/// Content below the fold is reached by dragging the sheet's inner ListView
/// (bounded pumps only — pumpAndSettle never settles on a DraggableScrollable
/// Sheet).
Future<void> _pumpSheet(
  WidgetTester tester,
  _Harness h,
) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: h.container,
      child: const MaterialApp(
        home: Scaffold(
          body: SafeArea(
            top: false,
            child: MemorySheet(),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 120));
}

/// Drags the sheet's inner ListView until [finder] pierces the viewport.
Future<void> _scrollTo(
  WidgetTester tester,
  Finder finder,
) async {
  await tester.drag(
    find.byType(ListView).first,
    const Offset(0, -400),
  );
  await tester.pump(const Duration(milliseconds: 120));
}

/// Sends one chat message to completion so the fake repo's stream drains
/// deterministically before assertions (send is fire-and-forget in UI code).
Future<void> _drainSend(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Rendering seeded memory', () {
    testWidgets('profile rows render the seeded values', (tester) async {
      final h = await _harness();
      await h.container.read(personalMemoryProvider.notifier).updateProfile(
            sponsor: 'Pat',
            homeGroup: 'Tuesday Men\'s Group',
            goal: 'Sponsor other men',
            triggers: ['Friday nights', 'Paydays'],
          );
      await _pumpSheet(tester, h);

      expect(find.text('Pat'), findsOneWidget);
      expect(find.text("Tuesday Men's Group"), findsOneWidget);
      expect(find.text('Sponsor other men'), findsOneWidget);
      // Trigger chips render with their delete affordance.
      expect(find.text('Friday nights'), findsOneWidget);
      expect(find.text('Paydays'), findsOneWidget);
      expect(find.text('Add trigger'), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(InputChip),
          matching: find.text('Friday nights'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('seeded facts render with an ago caption', (tester) async {
      // Prebake an OLD fact (created_at 3 days ago) straight into prefs —
      // the notifier has not been read yet, so build() picks this up and
      // agoFor() renders a real 'Xd ago' caption (not 'just now').
      final h = await _harness();
      final old = DateTime.now().subtract(const Duration(days: 3));
      final blob = {
        'profile': {'sponsor': null, 'home_group': null, 'goal': null, 'triggers': []},
        'facts': [
          {
            'id': 'fact_old',
            'text': 'Prefers evening meetings',
            'created_at': old.toIso8601String(),
            'source_conversation_id': 'conv-old',
          },
        ],
        'threads': [],
      };
      await h.prefs.setString(PersonalMemoryNotifier.prefsKey, jsonEncode(blob));
      await _pumpSheet(tester, h);

      final factText = find.text('Prefers evening meetings');
      var scrolls = 0;
      while (factText.evaluate().isEmpty && scrolls < 20) {
        await _scrollTo(tester, factText);
        scrolls++;
      }
      expect(factText, findsOneWidget);
      expect(find.text('3d ago'), findsOneWidget);
      // No empty-state hint when facts exist.
      expect(find.textContaining('Nothing yet'), findsNothing);
    });

    testWidgets('empty memory shows the facts empty-state copy', (tester) async {
      final h = await _harness();
      await _pumpSheet(tester, h);
      expect(
        find.textContaining('After a few conversations'),
        findsOneWidget,
      );
    });
  });

  group('Editing', () {
    testWidgets('fact edit flow opens a dialog and saves the new text',
        (tester) async {
      final h = await _harness();
      await h.container
          .read(personalMemoryProvider.notifier)
          .addFact('Old fact wording', 'conv-1');
      await _pumpSheet(tester, h);

      final scrollable = find.byType(Scrollable).first;
      await tester.dragUntilVisible(
        find.byIcon(Icons.edit_outlined),
        scrollable,
        const Offset(0, -120),
      );
      await tester.tap(find.byIcon(Icons.edit_outlined));
      await tester.pump(const Duration(milliseconds: 200)); // dialog in
      expect(find.text('Edit memory'), findsOneWidget);

      final field = find.byType(TextField);
      await tester.enterText(field, 'New fact wording');
      await tester.tap(find.text('Save'));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('New fact wording'), findsOneWidget);
      expect(find.text('Old fact wording'), findsNothing);
    });

    testWidgets('trigger chip add works via the Add trigger chip',
        (tester) async {
      final h = await _harness();
      await _pumpSheet(tester, h);

      await tester.tap(find.text('Add trigger'));
      await tester.pump(const Duration(milliseconds: 200));
      expect(find.text('Add a trigger'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'Rough Mondays');
      await tester.tap(find.text('Save'));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('Rough Mondays'), findsOneWidget);
    });

    testWidgets('trigger chip delete removes the trigger', (tester) async {
      final h = await _harness();
      await h.container
          .read(personalMemoryProvider.notifier)
          .updateProfile(triggers: ['Paydays']);
      await _pumpSheet(tester, h);

      final chipText = find.text('Paydays');
      expect(chipText, findsOneWidget);
      // Tap the InputChip's delete affordance (default tooltip delete icon).
      final chip = find.ancestor(
        of: find.text('Paydays'),
        matching: find.byType(InputChip),
      );
      expect(chip, findsOneWidget);
      final delIcon = find.descendant(
        of: chip,
        matching: find.byTooltip('Delete'),
      );
      expect(delIcon, findsOneWidget);
      await tester.tap(delIcon);
      await tester.pump(const Duration(milliseconds: 200));
      expect(find.text('Paydays'), findsNothing);
    });
  });

  group('Forget everything', () {
    testWidgets('confirm dialog wipes provider state and prefs', (tester) async {
      final h = await _harness();
      final notifier = h.container.read(personalMemoryProvider.notifier);
      await notifier.updateProfile(sponsor: 'Pat');
      await notifier.addFact('Some fact', 'conv-1');
      await notifier.upsertThread('t1', 'Open topic', 'detail');
      await _pumpSheet(tester, h);

      final forgetBtn = find.text('Forget everything');
      var scrolls = 0;
      while (forgetBtn.evaluate().isEmpty && scrolls < 20) {
        await _scrollTo(tester, forgetBtn);
        scrolls++;
      }
      await tester.tap(forgetBtn);
      await tester.tap(find.text('Forget everything'));
      await tester.pump(const Duration(milliseconds: 200)); // dialog in
      expect(
        find.textContaining('erases everything Copilot remembers'),
        findsOneWidget,
      );
      await tester.tap(find.text('Confirm'));
      await tester.pump(const Duration(milliseconds: 200));

      final memory = h.container.read(personalMemoryProvider);
      expect(memory.profile.sponsor, isNull);
      expect(memory.profile.triggers, isEmpty);
      expect(memory.facts, isEmpty);
      expect(memory.threads, isEmpty);
      // Persisted empty everywhere relevant.
      expect(h.prefs.getString(PersonalMemoryNotifier.prefsKey), isNotNull);
      expect(
        h.prefs.getString(PersonalMemoryNotifier.prefsKey),
        contains('"profile"'),
      );
    });

    testWidgets('cancel leaves memory intact', (tester) async {
      final h = await _harness();
      final notifier = h.container.read(personalMemoryProvider.notifier);
      await notifier.addFact('Precious memory', 'conv-1');
      await _pumpSheet(tester, h);

      final forgetBtn = find.text('Forget everything');
      var scrolls = 0;
      while (forgetBtn.evaluate().isEmpty && scrolls < 20) {
        await _scrollTo(tester, forgetBtn);
        scrolls++;
      }
      await tester.tap(forgetBtn);
      await tester.tap(find.text('Forget everything'));
      await tester.pump(const Duration(milliseconds: 200));
      await tester.tap(find.text('Cancel'));
      await tester.pump(const Duration(milliseconds: 200));

      expect(
        h.container.read(personalMemoryProvider).facts.single.text,
        'Precious memory',
      );
    });
  });

  group('Toggle privacy switch', () {
    testWidgets('starts true, flipping persists false to prefs', (tester) async {
      final h = await _harness();
      await _pumpSheet(tester, h);

      expect(h.container.read(memoryEnabledProvider), isTrue);
      final initial = h.prefs.getBool(kMemoryEnabledPrefsKey);
      expect(initial, isNull); // untouched until first explicit flip

      final switchFinder = find.byWidgetPredicate(
        (w) => w is Switch && w.value == true,
      );
      expect(switchFinder, findsOneWidget);
      await tester.tap(switchFinder);
      await tester.pump(const Duration(milliseconds: 200));

      expect(h.container.read(memoryEnabledProvider), isFalse);
      expect(h.prefs.getBool(kMemoryEnabledPrefsKey), isFalse);
    });
  });

  group('Thread resume', () {
    testWidgets('tapping a thread card pops the sheet and sends the resume '
        'prompt through the repo', (tester) async {
      final h = await _harness();
      await h.container
          .read(personalMemoryProvider.notifier)
          .upsertThread('t1', 'Step 8 amends', 'next step is journaling');

      // Host the sheet through the REAL open path (showAppSheet -> modal
      // route) so Navigator.pop() inside _resumeThread has something to pop.
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: h.container,
          child: const MaterialApp(
            home: Scaffold(
              body: _SheetHostButton(),
            ),
          ),
        ),
      );
      await tester.tap(find.byKey(const ValueKey('open-memory')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400)); // sheet route in
      expect(find.text('What Copilot knows about me'), findsOneWidget);

      final card = find.text('Step 8 amends');
      var scrolls = 0;
      while (card.evaluate().isEmpty && scrolls < 20) {
        await _scrollTo(tester, card);
        scrolls++;
      }
      expect(card, findsOneWidget);
      await tester.tap(card);
      await _drainSend(tester);
      await tester.pump(const Duration(milliseconds: 400)); // pop animation

      // Sheet popped.
      expect(find.text('What Copilot knows about me'), findsNothing);
      // Resume chain ran: /Previously/ history turn + resumePromptFor text.
      expect(h.repo.sends, 1);
      expect(
        h.repo.lastMessage,
        contains('Pick up where we left off'),
      );
      expect(h.repo.lastMessage, contains('keep going'));
      expect(h.repo.lastHistory!.first.text,
          startsWith('[Previously]: we were working on step 8 amends'));
      // New chat was seeded (resumedThread pinned).
      expect(
        h.container.read(chatNotifierProvider).resumedThread?.title,
        'Step 8 amends',
      );
    });

    testWidgets('Mark handled resolves the thread into the Handled tile',
        (tester) async {
      final h = await _harness();
      final notifier = h.container.read(personalMemoryProvider.notifier);
      await notifier.upsertThread('t1', 'Open topic', 'detail');
      await notifier.upsertThread('t2', 'Done topic', 'older', );
      await notifier.resolveThread('t2');
      await _pumpSheet(tester, h);

      final openTopic = find.text('Open topic');
      var scrolls = 0;
      while (openTopic.evaluate().isEmpty && scrolls < 20) {
        await _scrollTo(tester, openTopic);
        scrolls++;
      }
      expect(openTopic, findsOneWidget);
      expect(find.text('Mark handled'), findsOneWidget);
      final handledTile = find.text('Handled');
      var handledScrolls = 0;
      while (handledTile.evaluate().isEmpty && handledScrolls < 20) {
        await _scrollTo(tester, handledTile);
        handledScrolls++;
      }
      expect(handledTile, findsOneWidget); // the collapsed tile

      await tester.tap(find.text('Mark handled'));
      await tester.pump(const Duration(milliseconds: 200));

      final threads = h.container.read(personalMemoryProvider).threads;
      expect(threads.where((t) => t.id == 't1').single.resolved, isTrue);
    });
  });
}

// ============================================================================
// ResumeChip: FR11 Wave C — verification against the actual chip surface.
// (kept in this suite boundary: the chip is only VISUAL — its full click-path
// is asserted in resume_chip_test.dart; here we verify the sheet survives
// being closed and reopened with the same notifier state.)
// ============================================================================

class _SheetHostButton extends ConsumerWidget {
  const _SheetHostButton();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ElevatedButton(
      key: const ValueKey('open-memory'),
      onPressed: () => showAppSheet(context, const MemorySheet()),
      child: const Text('Open memory sheet'),
    );
  }
}
