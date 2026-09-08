// FR11.1 — 'Remember this' widget tests: the per-message save-to-memory
// affordance in ChatScreen.
//
// Riverpod widget-test pattern mirroring test/chat_notifier_memory_test.dart
// (fake streaming repo + shared_preferences mock at the provider seams) and
// test/resume_chip_test.dart (pumps the REAL ChatScreen with a ProviderContainer
// + UncontrolledProviderScope so provider state can be seeded and asserted).
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_screen.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/features/tts/tts_service.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

class FakeChatRepository implements ChatRepository {
  int sends = 0;
  String? lastMessage;

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
    yield const SourcesEvent([]);
    yield const TokenEvent('That sounds hard — thank you for sharing.');
    yield const DoneEvent();
  }
}

/// Inert TTS double (ChatScreen's initState binds TTS callbacks which would
/// otherwise race the test framework's pending-timers check).
class _FakeAppTts implements AppTts {
  @override
  void Function()? onDone;
  @override
  Future<void> stop() async {}
  @override
  Future<void> speak(String text) async {}
  @override
  void dispose() {}
}

class _Harness {
  _Harness(this.container, this.repo);
  final ProviderContainer container;
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
      appTtsProvider.overrideWithValue(_FakeAppTts()),
    ],
  );
  addTearDown(container.dispose);
  return _Harness(container, repo);
}

const String _userText =
    'I have a sponsor named Pat, and my home group is the Tuesday night group.';

/// Pumps the real ChatScreen with a completed (user → assistant) exchange so
/// bubbles render. Bounded pumps — no pumpAndSettle (perpetual animations).
Future<void> _pumpChat(WidgetTester tester, _Harness h) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: h.container,
      child: const MaterialApp(home: ChatScreen()),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 120));

  await h.container.read(chatNotifierProvider.notifier).sendMessage(_userText);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Remember this: affordance + dialog (FR11.1)', () {
    testWidgets('pin icon appears on user and assistant bubbles; long-press '
        'opens the prefilled dialog', (tester) async {
      final h = await _harness();
      await _pumpChat(tester, h);

      expect(find.text(_userText), findsOneWidget);
      expect(
        find.text('That sounds hard — thank you for sharing.'),
        findsOneWidget,
      );
      // The affordance shows for BOTH roles.
      final pins = find.byTooltip('Remember this');
      expect(pins, findsNWidgets(2));

      // Long-press the USER bubble's pin.
      final container = h.container.read(personalMemoryProvider);
      expect(container.facts, isEmpty);
      await tester.longPress(pins.first);
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Remember this'), findsOneWidget);
      final dialogField = find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byType(TextField),
      );
      expect(dialogField, findsOneWidget);
      final tf = tester.widget<TextField>(dialogField);
      expect(tf.controller!.text, _userText);
      expect(
        find.text(
          'Saved on this device. Copilot will use it as context in '
          'future chats.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('Save stores the fact under the live conversation id and '
        'shows the snackbar', (tester) async {
      final h = await _harness();
      await _pumpChat(tester, h);

      await tester.longPress(find.byTooltip('Remember this').first);
      await tester.pump(const Duration(milliseconds: 300));

      await tester.enterText(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(TextField),
        ),
        'Sponsor is Pat',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.textContaining('Saved to your memory'), findsOneWidget);
      final mem = h.container.read(personalMemoryProvider);
      expect(mem.facts, hasLength(1));
      expect(mem.facts.single.text, 'Sponsor is Pat');
      expect(
        mem.facts.single.sourceConversationId,
        h.container.read(chatNotifierProvider).conversationId,
      );
    });

    testWidgets('UNDO removes the just-added fact', (tester) async {
      final h = await _harness();
      await _pumpChat(tester, h);

      await tester.longPress(find.byTooltip('Remember this').first);
      await tester.pump(const Duration(milliseconds: 300));
      await tester.enterText(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(TextField),
        ),
        'Sponsor is Pat',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 200));
      await tester.pump(const Duration(milliseconds: 200));

      await tester.tap(find.widgetWithText(TextButton, 'UNDO'));
      await tester.pump(); // snackbar action tap
      await tester.pump(const Duration(milliseconds: 50));
      // Let the snackbar time out drain its timers deterministically.
      await tester.pump(const Duration(seconds: 4));

      expect(h.container.read(personalMemoryProvider).facts, isEmpty);
    });

    testWidgets('empty prefilled text disables Save', (tester) async {
      final h = await _harness();
      await _pumpChat(tester, h);

      await tester.longPress(find.byTooltip('Remember this').first);
      await tester.pump(const Duration(milliseconds: 300));
      await tester.enterText(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(TextField),
        ),
        '   ',
      );
      await tester.pump();

      final save = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Save'),
      );
      expect(save.onPressed, isNull);
    });

    testWidgets('re-saving an identical fact shows Already in your memory '
        'instead of duplicating', (tester) async {
      final h = await _harness();
      await _pumpChat(tester, h);

      final notifier = h.container.read(personalMemoryProvider.notifier);
      await notifier.addFact(
        'Sponsor is Pat',
        h.container.read(chatNotifierProvider).conversationId!,
      );

      await tester.longPress(find.byTooltip('Remember this').first);
      await tester.pump(const Duration(milliseconds: 300));
      await tester.enterText(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(TextField),
        ),
        'Sponsor is Pat',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.textContaining('Already in your memory'), findsOneWidget);
      final mem = h.container.read(personalMemoryProvider);
      expect(mem.facts, hasLength(1));
    });

    testWidgets('Cancel discards: no fact added, no snackbar', (tester) async {
      final h = await _harness();
      await _pumpChat(tester, h);

      await tester.longPress(find.byTooltip('Remember this').first);
      await tester.pump(const Duration(milliseconds: 300));
      await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.textContaining('Saved to your memory'), findsNothing);
      expect(h.container.read(personalMemoryProvider).facts, isEmpty);
    });
  });
}
