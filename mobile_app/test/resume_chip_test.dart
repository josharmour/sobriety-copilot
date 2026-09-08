// FR11 Wave C — resume-chip widget tests (empty-chat state).
//
// Pumps the REAL ChatScreen through ProviderScope overrides (per the
// FR-plan widget-test pattern) with a fake chatRepository at the seam. The
// chip lives on the empty-state StarterView; the fake must accept the
// resumePromptFor text ('Pick up where we left off … keep going').
//
// The harness overrides appTtsProvider with an inert fake: ChatScreen's
// initState binds TTS completion callbacks which would otherwise race the
// test framework's pending-timers check.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_screen.dart';
import 'package:sobriety_copilot_mobile/features/tts/tts_service.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

class FakeChatRepository implements ChatRepository {
  int sends = 0;
  String? lastMessage;
  List<ChatMessage>? lastHistory;

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
    yield const SourcesEvent([]);
    yield const TokenEvent('Picking that back up.');
    yield const DoneEvent();
  }
}

/// Inert TTS double: satisfies the AppTts interface without platform
/// channels/timers (ChatScreen initState binds its callbacks; these tests
/// never trigger a speak).
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

final DateTime _t = DateTime(2026, 9, 1);

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

Future<void> _pumpScreen(WidgetTester tester, _Harness h) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: h.container,
      child: const MaterialApp(home: ChatScreen()),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 120));
}

/// The chip sends are fire-and-forget; drain the fake's stream with bounded
/// pumps (no pumpAndSettle — the starter view has perpetual gradients in
/// dark mode).
Future<void> _drain(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('empty chat + one open thread: chip renders and tapping it '
      'resumes through the fake repo', (tester) async {
    final h = await _harness();
    await h.container
        .read(personalMemoryProvider.notifier)
        .upsertThread('t1', 'Step 8 amends', 'next step: honest inventory');

    await _pumpScreen(tester, h);

    final chip = find.text('Continue: Step 8 amends');
    expect(chip, findsOneWidget);

    await tester.tap(chip);
    await _drain(tester);

    // startNew + resumeThread + sendMessage(resumePromptFor) all ran.
    expect(h.repo.sends, 1);
    expect(
      h.repo.lastMessage,
      contains('Pick up where we left off'),
    );
    expect(h.repo.lastMessage, contains('keep going'));
    expect(h.repo.lastHistory!.first.text,
        startsWith('[Previously]: we were working on step 8 amends'));
    final chat = h.container.read(chatNotifierProvider);
    expect(chat.resumedThread?.title, 'Step 8 amends');
    // The send actually started: user + placeholder are in the live state.
    expect(chat.messages.first.text,
        startsWith('Pick up where we left off'));
  });

  testWidgets('memory disabled: chip absent', (tester) async {
    final h = await _harness();
    await h.container
        .read(personalMemoryProvider.notifier)
        .upsertThread('t1', 'Step 8 amends', 'next step: honest inventory');
    await h.container
        .read(memoryEnabledProvider.notifier)
        .setEnabled(false);

    await _pumpScreen(tester, h);
    expect(find.textContaining('Continue:'), findsNothing);
  });

  testWidgets('resolved-only threads: chip absent', (tester) async {
    final h = await _harness();
    final notifier = h.container.read(personalMemoryProvider.notifier);
    await notifier.upsertThread('t1', 'Step 8 amends', 'older');
    await notifier.resolveThread('t1');

    await _pumpScreen(tester, h);
    expect(find.textContaining('Continue:'), findsNothing);
  });

  testWidgets('resumedThread already set: chip absent', (tester) async {
    final h = await _harness();
    await h.container
        .read(personalMemoryProvider.notifier)
        .upsertThread('t1', 'Step 8 amends', 'next step');
    final chatNotifier = h.container.read(chatNotifierProvider.notifier);
    chatNotifier.resumeThread(
      MemoryThread(
        id: 't1',
        title: 'Step 8 amends',
        lastDetail: 'next step',
        updatedAt: _t,
      ),
    );

    await _pumpScreen(tester, h);
    expect(find.textContaining('Continue:'), findsNothing);
  });
}
