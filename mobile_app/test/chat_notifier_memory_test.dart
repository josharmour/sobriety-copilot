// FR11 Wave B — ChatNotifier wiring tests: clientContext snapshot merge,
// resumed-thread retrieval hook ([Previously]: synthetic turn), and the
// conversation-end distillation hook (exactly once per conversation id,
// memory grows via personalMemoryProvider, failures stay silent).
//
// Notifier-test pattern (required by the FR plans): a ProviderContainer with
// sharedPreferencesProvider + chatRepositoryProvider + distillerProvider
// overrides — never instantiate ChatNotifier directly.

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_notifier.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_distiller.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Emits Sources/Token/Done and records the last request for assertions.
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
    yield const TokenEvent('That sounds hard — thank you for sharing.');
    yield const DoneEvent();
  }
}

/// Recording distiller injected via distillerProvider — the required test
/// seam. No network, no model.
class RecordingDistiller implements MemoryDistiller {
  int calls = 0;
  List<ChatMessage>? lastTranscript;
  Map<String, dynamic>? lastDigest;
  DistillResult result = const DistillResult(newFacts: [], threads: []);
  Object? error;

  @override
  DistillTransport get transport =>
      throw UnimplementedError('recording distiller has no transport');

  @override
  Future<DistillResult> distill(
    List<ChatMessage> transcript, {
    Map<String, dynamic>? existingMemoryDigest,
  }) async {
    calls++;
    lastTranscript = List<ChatMessage>.from(transcript);
    lastDigest = existingMemoryDigest;
    final e = error;
    if (e != null) throw e;
    return result;
  }
}


ChatMessage _assistant(String text) => ChatMessage(
      id: 'a-${text.hashCode}',
      role: 'assistant',
      text: text,
      createdAt: DateTime(2026, 9, 7),
    );

class _Harness {
  _Harness(this.container, this.repo, this.distiller);
  final ProviderContainer container;
  final FakeChatRepository repo;
  final RecordingDistiller distiller;
}

Future<_Harness> _harness({RecordingDistiller? distiller}) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final repo = FakeChatRepository();
  final rec = distiller ?? RecordingDistiller();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      chatRepositoryProvider.overrideWithValue(repo),
      distillerProvider.overrideWithValue(rec),
    ],
  );
  addTearDown(container.dispose);
  return _Harness(container, repo, rec);
}

/// Sends one message to completion, then flushes the fire-and-forget
/// distillation + prefs writes (microtasks only; nothing here is timered).
Future<void> _send(_Harness h, String text) async {
  await h.container.read(chatNotifierProvider.notifier).sendMessage(text);
  await pumpEventQueue();
}

ChatNotifier _notifier(_Harness h) =>
    h.container.read(chatNotifierProvider.notifier);

const DistillResult _cannedResult = DistillResult(
  newFacts: ['Prefers evening meetings over morning ones'],
  threads: [
    DistilledThread(
      id: 'step-8-amends',
      title: 'Step 8 amends list',
      detail: 'Working out who to write to',
      resolved: false,
    ),
  ],
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('clientContext merge (FR11 snapshot)', () {
    test('injects snapshot when memory exists; nothing when empty', () async {
      final h = await _harness();
      final mem = h.container.read(personalMemoryProvider.notifier);
      await mem.updateProfile(
        triggers: ['Friday nights alone'],
        goal: 'Stay sober one day at a time',
      );
      await mem.addFact('Prefers evening meetings', 'seed-conv');

      await _send(h, 'Just checking in');
      expect(h.repo.lastClientContext, isNotNull);
      expect(h.repo.lastClientContext, contains('Prefers evening meetings'));
      expect(h.repo.lastClientContext, contains('Friday nights alone'));
      expect(h.repo.lastClientContext, contains('do not recite'));
      expect(h.repo.lastClientContext!.length, lessThanOrEqualTo(600));

      // A genuinely empty memory (fresh device state) sends no clientContext
      // when the question is not a day-count question.
      final h2 = await _harness();
      await _send(h2, 'Hi');
      expect(h2.repo.lastClientContext, isNull);
    });

    test('keeps the day-count line AND appends the snapshot', () async {
      final h = await _harness();
      final sobriety = h.container.read(sobrietyProvider.notifier);
      sobriety.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      final mem = h.container.read(personalMemoryProvider.notifier);
      await mem.addFact('Prefers evening meetings', 'seed-conv');

      await _send(h, 'How many days sober am I?');
      expect(h.repo.lastClientContext, contains('days sober'));
      expect(h.repo.lastClientContext, contains('Prefers evening meetings'));
      expect(h.repo.lastClientContext, contains('do not recite'));
    });
  });

  group('distillation hook (FR11 Task 3)', () {
    test('no distill call when the conversation is under 4 messages', () async {
      final h = await _harness();
      await _send(h, 'First message');
      expect(h.repo.sends, 1);
      expect(h.distiller.calls, 0);
    });

    test('distills once per conversation id; memory grows; no growth on '
        'second Done', () async {
      final h = await _harness();
      h.distiller.result = _cannedResult;

      await _send(h, 'First message');
      await _send(h, 'Second message'); // 4 messages -> qualifies
      expect(h.distiller.calls, 1);
      expect(h.distiller.lastTranscript, hasLength(4));

      final memory = h.container.read(personalMemoryProvider);
      expect(memory.facts.single.text, 'Prefers evening meetings over morning ones');
      expect(memory.facts.single.sourceConversationId,
          h.container.read(chatNotifierProvider).conversationId);
      expect(memory.threads.single.title, 'Step 8 amends list');

      // A third send on the SAME conversation must not distill again.
      await _send(h, 'Third message');
      expect(h.distiller.calls, 1);
      expect(h.container.read(personalMemoryProvider).facts, hasLength(1));
      expect(h.container.read(personalMemoryProvider).threads, hasLength(1));
    });

    test('digest carries known fact texts and open thread titles', () async {
      final h = await _harness();
      final mem = h.container.read(personalMemoryProvider.notifier);
      await mem.addFact('Seeded known fact', 'seed-conv');
      await mem.upsertThread('t1', 'Open thread title', 'detail');

      await _send(h, 'First message');
      await _send(h, 'Second message');
      expect(h.distiller.calls, 1);
      final facts = h.distiller.lastDigest!['facts'] as List<dynamic>;
      expect(facts, contains('Seeded known fact'));
      final threads = h.distiller.lastDigest!['threads'] as List<dynamic>;
      expect(threads, contains('Open thread title'));
    });

    test('memory OFF: no snapshot in the sent body (day-count unaffected)',
        () async {
      final h = await _harness();
      await h.container
          .read(memoryEnabledProvider.notifier)
          .setEnabled(false);
      final sobriety = h.container.read(sobrietyProvider.notifier);
      sobriety.state = SobrietyState(sobrietyDate: DateTime(2026, 1, 1));
      final mem = h.container.read(personalMemoryProvider.notifier);
      await mem.addFact('Prefers evening meetings', 'seed-conv');
      await mem.upsertThread('t1', 'Open thread title', 'detail');

      await _send(h, 'How many days sober am I?');
      // The day-count line survives (that feature has its own switch, the
      // tracker), but NO memory snapshot is merged in.
      expect(h.repo.lastClientContext, isNotNull);
      expect(h.repo.lastClientContext, contains('days sober'));
      expect(
        h.repo.lastClientContext,
        isNot(contains('Prefers evening meetings')),
      );
      expect(h.repo.lastClientContext, isNot(contains('Currently discussing')));
      expect(h.repo.lastClientContext, isNot(contains('do not recite')));
    });

    test('memory OFF after >4 qualifying messages still triggers no distill '
        'calls', () async {
      final h = await _harness();
      await h.container
          .read(memoryEnabledProvider.notifier)
          .setEnabled(false);
      h.distiller.result = _cannedResult;

      await _send(h, 'First message');
      await _send(h, 'Second message'); // 4 -> would qualify without the gate
      expect(h.distiller.calls, 0);
      expect(
        h.container.read(personalMemoryProvider).facts,
        isEmpty,
      );

      // Memory re-enabled: the NEXT conversation distills normally (the
      // disabled conversation is discarded, not queued).
      await h.container
          .read(memoryEnabledProvider.notifier)
          .setEnabled(true);
      await _send(h, 'Third message');
      await _send(h, 'Fourth message'); // fresh 4-message conversation
      expect(h.distiller.calls, 1);
      expect(
        h.container.read(personalMemoryProvider).facts,
        hasLength(1),
      );
    });

    test('memory ON (default): snapshot still present, distill still runs',
        () async {
      final h = await _harness();
      final mem = h.container.read(personalMemoryProvider.notifier);
      await mem.addFact('Prefers evening meetings', 'seed-conv');
      h.distiller.result = _cannedResult;

      await _send(h, 'First message');
      await _send(h, 'Second message');
      expect(h.repo.lastClientContext, contains('Prefers evening meetings'));
      expect(h.distiller.calls, 1);
    });

    test('resolved=true thread resolves the matching existing thread via the '
        'memory ledger', () async {
      final h = await _harness();
      final mem = h.container.read(personalMemoryProvider.notifier);
      await mem.upsertThread('t1', 'Step 8 amends list', 'who to write to');
      h.distiller.result = const DistillResult(
        newFacts: [],
        threads: [
          DistilledThread(
            id: 'model-new-id',
            title: 'Step 8 amends list',
            detail: 'done',
            resolved: true,
          ),
        ],
      );

      await _send(h, 'First message');
      await _send(h, 'Second message');

      final threads = h.container.read(personalMemoryProvider).threads;
      expect(threads, hasLength(1)); // no new thread created
      expect(threads.single.id, 't1'); // resolved the EXISTING thread
      expect(threads.single.resolved, isTrue);
    });

    test('distill failure is silent: chat state untouched, no memory growth',
        () async {
      final h = await _harness();
      h.distiller.error = const MemoryDistillError('boom');

      await _send(h, 'First message');
      await _send(h, 'Second message');
      expect(h.distiller.calls, 1);
      expect(h.container.read(chatNotifierProvider).isSending, isFalse);
      expect(h.container.read(chatNotifierProvider).error, isNull);
      expect(h.container.read(personalMemoryProvider).facts, isEmpty);
      expect(h.container.read(personalMemoryProvider).threads, isEmpty);
    });
  });

  group('DistillTransport product path (FR11 Wave B)', () {
    const base = 'https://sobrietycopilot.com';

    test('forBackend picks local vs server transport', () {
      Future<String> localGen(String p) async => p;
      final local = DistillTransport.forBackend(
        privateMode: true,
        serverBaseUrl: base,
        localGenerator: localGen,
      );
      expect(local, isA<LocalDistillTransport>());

      // Private Mode but no usable generator -> server fallback.
      final noGen = DistillTransport.forBackend(
        privateMode: true,
        serverBaseUrl: base,
        localGenerator: null,
      );
      expect(noGen, isA<ServerDistillTransport>());

      // Server mode -> product ServerDistillTransport (base URL preserved).
      final server = DistillTransport.forBackend(
        privateMode: false,
        serverBaseUrl: base,
      );
      expect(server, isA<ServerDistillTransport>());
      expect((server as ServerDistillTransport).baseUrl, base);
    });

    test('distill() routes through /api/distill and parses the response',
        () async {
      late http.Request captured;
      final client = MockClient((req) async {
        captured = req;
        return http.Response(
          '{"new_facts":["Prefers evening meetings"],'
          '"threads":[{"id":"a-b","title":"A B","detail":"d","resolved":false}]}',
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final d = MemoryDistiller(
        transport: DistillTransport.forBackend(
          privateMode: false,
          serverBaseUrl: base,
          client: client,
        ),
      );
      final out = await d.distill(
        [
          ChatMessage.user('hello'),
          _assistant('hi back'),
        ],
        existingMemoryDigest: {
          'facts': ['Known'],
          'threads': ['Open'],
        },
      );
      expect(captured.method, 'POST');
      expect(captured.url.toString(), '$base/api/distill');
      final body = jsonDecode(captured.body) as Map<String, dynamic>;
      final transcript = body['transcript'] as List<dynamic>;
      expect(transcript.first['role'], 'user');
      expect(transcript.first['content'], 'hello');
      expect((body['existing'] as Map)['facts'], ['Known']);
      expect(out.newFacts.single, 'Prefers evening meetings');
      expect(out.threads.single.id, 'a-b');
    });

    test('product transport non-200 throws MemoryDistillError', () async {
      final client = MockClient((_) async => http.Response('nope', 500));
      final d = MemoryDistiller(
        transport: ServerDistillTransport(baseUrl: base, client: client),
      );
      expect(
        d.distill([ChatMessage.user('x'), _assistant('y')]),
        throwsA(isA<MemoryDistillError>()),
      );
    });

    test('product transport malformed JSON body throws MemoryDistillError',
        () async {
      final client =
          MockClient((_) async => http.Response('not json', 200));
      final d = MemoryDistiller(
        transport: ServerDistillTransport(baseUrl: base, client: client),
      );
      expect(
        d.distill([ChatMessage.user('x'), _assistant('y')]),
        throwsA(isA<MemoryDistillError>()),
      );
    });
  });

  group('resumed-thread retrieval hook (FR11 Task 5)', () {
    test('resumeThread pins state and prepends [Previously]: on the FIRST '
        'send only', () async {
      final h = await _harness();
      final notifier = _notifier(h);
      final thread = MemoryThread(
        id: 'step-8',
        title: 'Step 8 amends',
        lastDetail: 'listing people',
        updatedAt: _t,
      );
      notifier.resumeThread(thread);

      expect(h.container.read(chatNotifierProvider).resumedThread?.title,
          'Step 8 amends');

      await _send(h, 'Pick up where we left off');
      final first = h.repo.lastHistory!.first;
      expect(first.text, startsWith('[Previously]:'));
      expect(first.text, contains('step 8 amends'));
      expect(first.text, contains('listing people'));
      // The sent message itself stays what the UI passed.
      expect(h.repo.lastMessage, 'Pick up where we left off');

      // Second send: no re-injection; the pinned note survives for the UI.
      await _send(h, 'Following up');
      expect(h.repo.lastHistory!.first.text, isNot(startsWith('[Previously]:')));
      expect(h.container.read(chatNotifierProvider).resumedThread, isNotNull);
    });

    test('a resumed thread with no detail drops the em-dash clause', () async {
      final h = await _harness();
      final notifier = _notifier(h);
      notifier.resumeThread(MemoryThread(
        id: 't2',
        title: 'Step Nine',
        updatedAt: _t,
      ));
      await _send(h, 'Go');
      expect(h.repo.lastHistory!.first.text, '[Previously]: we were working on step nine');
    });

    test('startNew clears resumedThread', () async {
      final h = await _harness();
      final notifier = _notifier(h);
      notifier.resumeThread(MemoryThread(
        id: 't3',
        title: 'Inventory',
        updatedAt: _t,
      ));
      expect(h.container.read(chatNotifierProvider).resumedThread, isNotNull);
      notifier.startNew();
      expect(h.container.read(chatNotifierProvider).resumedThread, isNull);
    });
  });
}

final DateTime _t = DateTime(2026, 9, 7);
