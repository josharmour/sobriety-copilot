// FR11 Task 2 — MemoryDistiller + transports.
//
// One-shot LLM extraction at conversation END: last 12 turns of a transcript
// -> durable facts + open threads. Fully offline: a recording fake transport
// captures the prompt; no network anywhere in this file.
//
// Contract notes for Task 3 (chat_notifier wiring):
//   - MemoryDistiller.distill() throws MemoryDistillError on malformed JSON
//     (never retries). ChatNotifier must catch and silently skip.
//   - DistilledThread maps onto personal_memory.dart's MemoryThread; the
//     digest param carries already-known fact/thread titles for dedupe.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_distiller.dart';

/// Captures the prompt it was given and answers with a canned raw completion
/// (or rethrows a configured error). No network.
class RecordingDistillTransport implements DistillTransport {
  RecordingDistillTransport({this.response = '', this.error});

  String response;
  Object? error;
  String? lastPrompt;
  int calls = 0;

  @override
  Future<String> complete(String prompt) async {
    calls++;
    lastPrompt = prompt;
    final e = error;
    if (e != null) throw e;
    return response;
  }
}

ChatMessage _msg(String id, String role, String text) => ChatMessage(
      id: id,
      role: role,
      text: text,
      createdAt: DateTime(2026, 9, 7),
    );

List<ChatMessage> _transcript(int count) => [
      for (var i = 1; i <= count; i++)
        _msg(
          'id-$i',
          i.isOdd ? 'user' : 'assistant',
          'msg-${i.toString().padLeft(2, '0')}-content',
        ),
    ];

MemoryDistiller _distiller(RecordingDistillTransport t) =>
    MemoryDistiller(transport: t);

const String _cannedJson =
    '{"new_facts":["Prefers evening meetings over morning ones",'
    '"Working Step Four with his sponsor"],'
    '"threads":[{"id":"step-8-amends","title":"Step 8 amends list",'
    '"detail":"Working out who to write to","resolved":false}]}';

void main() {
  group('MemoryDistiller parsing', () {
    test('canned JSON parses into newFacts and threads', () async {
      final t = RecordingDistillTransport(response: _cannedJson);
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts, hasLength(2));
      expect(out.newFacts.first, contains('evening meetings'));
      expect(out.threads, hasLength(1));
      expect(out.threads.single.id, 'step-8-amends');
      expect(out.threads.single.title, 'Step 8 amends list');
      expect(out.threads.single.detail, 'Working out who to write to');
      expect(out.threads.single.resolved, isFalse);
    });

    test('empty arrays mean nothing worth remembering', () async {
      final t = RecordingDistillTransport(
        response: '{"new_facts":[],"threads":[]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts, isEmpty);
      expect(out.threads, isEmpty);
    });

    test('malformed JSON throws MemoryDistillError', () async {
      final t = RecordingDistillTransport(response: 'this is not json at all');
      expect(
        _distiller(t).distill(_transcript(6)),
        throwsA(isA<MemoryDistillError>()),
      );
    });

    test('truncated JSON (unclosed) throws MemoryDistillError', () async {
      final t = RecordingDistillTransport(
        response: '{"new_facts":["Prefers evening meetings"],"threads":[',
      );
      expect(
        _distiller(t).distill(_transcript(6)),
        throwsA(isA<MemoryDistillError>()),
      );
    });

    test('markdown-fenced JSON parses', () async {
      final t = RecordingDistillTransport(
        response: '```json\n$_cannedJson\n```',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts, hasLength(2));
      expect(out.threads.single.title, 'Step 8 amends list');
    });

    test('JSON buried in prose parses via first-{...} fallback', () async {
      final t = RecordingDistillTransport(
        response: 'Sure, here you go:\n$_cannedJson\nHope that helps!',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts, hasLength(2));
    });

    test('oversized fact is truncated to 120 chars', () async {
      final long = 'x' * 200;
      final t = RecordingDistillTransport(
        response: '{"new_facts":["$long"],"threads":[]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts.single.length, 120);
      expect(out.newFacts.single, startsWith('x' * 120));
    });

    test('thread title capped at 50, detail at 120', () async {
      final t = RecordingDistillTransport(
        response:
            '{"new_facts":[],"threads":[{"id":"a-b","title":"${'t' * 80}",'
            '"detail":"${'d' * 200}","resolved":false}]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.threads.single.title.length, 50);
      expect(out.threads.single.detail.length, 120);
    });

    test('more than 3 facts are capped at 3', () async {
      final t = RecordingDistillTransport(
        response:
            '{"new_facts":["f1","f2","f3","f4","f5"],"threads":[]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts, ['f1', 'f2', 'f3']);
    });

    test('more than 2 threads are capped at 2', () async {
      final t = RecordingDistillTransport(
        response:
            '{"new_facts":[],"threads":[{"id":"a","title":"A","detail":"","resolved":false},'
            '{"id":"b","title":"B","detail":"","resolved":false},'
            '{"id":"c","title":"C","detail":"","resolved":false}]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.threads.map((e) => e.id), ['a', 'b']);
    });

    test('non-string garbage in new_facts is dropped', () async {
      final t = RecordingDistillTransport(
        response:
            '{"new_facts":["keep me",42,null,true,{"x":1},123.4],"threads":[]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.newFacts, ['keep me']);
    });

    test('non-map garbage in threads is dropped', () async {
      final t = RecordingDistillTransport(
        response:
            '{"new_facts":[],"threads":["nope",42,{"id":"ok","title":"Fine",'
            '"detail":"","resolved":false},null]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.threads.single.id, 'ok');
    });

    test('resolved:true is preserved', () async {
      final t = RecordingDistillTransport(
        response:
            '{"new_facts":[],"threads":[{"id":"done-x","title":"Done",'
            '"detail":"","resolved":true}]}',
      );
      final out = await _distiller(t).distill(_transcript(6));
      expect(out.threads.single.resolved, isTrue);
    });
  });

  group('MemoryDistiller prompt construction', () {
    test('only the last 12 turns appear in the prompt', () async {
      final t = RecordingDistillTransport(response: _cannedJson);
      await _distiller(t).distill(_transcript(14));
      final prompt = t.lastPrompt!;
      // Messages 3..14 (12 of them) must be present…
      for (var i = 3; i <= 14; i++) {
        final tag = 'msg-${i.toString().padLeft(2, '0')}-content';
        expect(prompt, contains(tag), reason: 'turn $i should be in prompt');
      }
      // …and messages 1..2 must not.
      expect(prompt, isNot(contains('msg-01-content')));
      expect(prompt, isNot(contains('msg-02-content')));
    });

    test('all turns appear when transcript has fewer than 12', () async {
      final t = RecordingDistillTransport(response: _cannedJson);
      await _distiller(t).distill(_transcript(4));
      final prompt = t.lastPrompt!;
      for (var i = 1; i <= 4; i++) {
        expect(prompt, contains('msg-0$i-content'));
      }
    });

    test('error turns are excluded from the prompt', () async {
      // 13 clean turns (msg-01..msg-13) + one error turn. The error must be
      // dropped entirely, and its slot must NOT displace a clean turn: with
      // 13 clean turns the window is msg-02..msg-13, so msg-01 is dropped but
      // msg-02 is kept. If the error were counted as a turn the window would
      // be msg-03..msg-13 plus the error text.
      final clean = _transcript(13);
      final err = ChatMessage(
        id: 'e1',
        role: 'assistant',
        text: 'whoops broken',
        createdAt: DateTime(2026, 9, 7),
        isError: true,
      );
      final all = [...clean, err];
      final t = RecordingDistillTransport(response: _cannedJson);
      await _distiller(t).distill(all);
      expect(t.lastPrompt, isNot(contains('whoops broken')));
      expect(t.lastPrompt, isNot(contains('msg-01-content')));
      expect(t.lastPrompt, contains('msg-02-content'));
      expect(t.lastPrompt, contains('msg-13-content'));
    });

    test('existing memory digest titles are included for dedupe', () async {
      final t = RecordingDistillTransport(response: _cannedJson);
      await _distiller(t).distill(
        _transcript(6),
        existingMemoryDigest: {
          'facts': ['Prefers evening meetings', 'Loves his sponsor'],
          'threads': ['Step 4 inventory'],
        },
      );
      final prompt = t.lastPrompt!;
      expect(prompt, contains('Prefers evening meetings'));
      expect(prompt, contains('Loves his sponsor'));
      expect(prompt, contains('Step 4 inventory'));
    });

    test('transcript is rendered with user/assistant roles', () async {
      final t = RecordingDistillTransport(response: _cannedJson);
      await _distiller(t).distill(_transcript(2));
      final prompt = t.lastPrompt!;
      expect(prompt, contains('User: msg-01-content'));
      expect(prompt, contains('Assistant: msg-02-content'));
    });

    test('a transport error propagates out of distill unchanged', () async {
      final t = RecordingDistillTransport(
        error: const MemoryDistillError('server transport failed'),
      );
      expect(
        _distiller(t).distill(_transcript(6)),
        throwsA(isA<MemoryDistillError>()),
      );
    });
  });

  group('ServerDistillTransport (legacy direct path removed)', () {
    const base = 'http://inference.local:11434';

    test('complete() fails fast: server mode must use completeProduct', () {
      // The legacy OpenAI-compatible direct-to-inference path was removed
      // (review note: dead code that widened the server-visible surface).
      // distill() routes ServerDistillTransport through completeProduct()
      // automatically; calling complete() is a programming error.
      final transport = ServerDistillTransport(
        baseUrl: base,
        client: MockClient((_) async => http.Response('{}', 200)),
      );
      expect(
        transport.complete('distill me'),
        throwsA(isA<MemoryDistillError>()),
      );
    });

    test('distill() via product passthrough POSTs /api/distill', () async {
      late http.Request captured;
      final client = MockClient((req) async {
        captured = req;
        return http.Response(
          '{"new_facts":["ok"],"threads":[]}',
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final d = MemoryDistiller(
        transport: ServerDistillTransport(baseUrl: base, client: client),
      );
      final out = await d.distill([
        ChatMessage.user('hello'),
        ChatMessage(
          id: 'a2',
          role: 'assistant',
          text: 'so glad you asked',
          createdAt: DateTime.now(),
        ),
      ]);
      expect(captured.method, 'POST');
      expect(captured.url.toString(), '$base/api/distill');
      expect(captured.headers['content-type'], contains('application/json'));
      final body = jsonDecode(captured.body) as Map<String, dynamic>;
      final transcript = body['transcript'] as List<dynamic>;
      expect(transcript.length, 2);
      expect(out.newFacts, ['ok']);
    });

    test('distill() non-200 throws MemoryDistillError', () async {
      final client =
          MockClient((_) async => http.Response('nope', 500));
      final d = MemoryDistiller(
        transport: ServerDistillTransport(baseUrl: base, client: client),
      );
      expect(
        d.distill([ChatMessage.user('x'), ChatMessage.user('y')]),
        throwsA(isA<MemoryDistillError>()),
      );
    });

    test('distill() network exception throws MemoryDistillError', () async {
      final client = MockClient(
        (_) async => throw http.ClientException('connection refused'),
      );
      final d = MemoryDistiller(
        transport: ServerDistillTransport(baseUrl: base, client: client),
      );
      expect(
        d.distill([ChatMessage.user('x'), ChatMessage.user('y')]),
        throwsA(isA<MemoryDistillError>()),
      );
    });
  });

  group('LocalDistillTransport', () {
    test('delegates to the provided generator', () async {
      String? seen;
      final transport = LocalDistillTransport(
        generator: (prompt) async {
          seen = prompt;
          return '{"new_facts":["x"],"threads":[]}';
        },
      );
      expect(await transport.complete('hi'), contains('new_facts'));
      expect(seen, 'hi');
    });

    test('throws MemoryDistillError when no generator is wired', () {
      final transport = LocalDistillTransport();
      expect(
        transport.complete('hi'),
        throwsA(isA<MemoryDistillError>()),
      );
    });
  });
}
