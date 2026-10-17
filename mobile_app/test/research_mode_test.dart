// Research mode (/api/research) and the concept graph's compact map format.
//
// Notifier tests follow the usual pattern: a ProviderContainer with
// repository overrides — the research repository is its own provider so the
// chat repository (and every fake implementing it) is untouched.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/features/graph2/concept_models.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_distiller.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

class _ScriptedRepo implements ChatRepository {
  _ScriptedRepo(this.events);
  final List<ChatEvent> events;
  int sends = 0;
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
    lastHistory = List<ChatMessage>.from(history);
    for (final e in events) {
      yield e;
    }
  }
}

class _NoDistill implements MemoryDistiller {
  @override
  DistillTransport get transport => throw UnimplementedError();

  @override
  Future<DistillResult> distill(List<ChatMessage> transcript,
          {Map<String, dynamic>? existingMemoryDigest, bool suggestMode = false}) async =>
      const DistillResult(newFacts: [], threads: []);
}

ChatEvent _ev(Map<String, dynamic> j) => ChatEvent.fromJson(j)!;

final List<ChatEvent> _researchScript = [
  _ev({'research': {'type': 'phase', 'phase': 'researching'}}),
  _ev({'research': {'type': 'step', 'id': 1, 'tool': 'read_section', 'label': 'Reading “How It Works”', 'status': 'running'}}),
  _ev({'research': {'type': 'step', 'id': 1, 'tool': 'read_section', 'label': 'Reading “How It Works”', 'status': 'done', 'detail': '3,679 words'}}),
  _ev({'research': {'type': 'step', 'id': 2, 'tool': 'analyze_sections', 'label': 'Reading 11 sections', 'status': 'running', 'progress': [4, 11]}}),
  _ev({'research': {'type': 'phase', 'phase': 'writing'}}),
  const TokenEvent('The Third Step prayer '),
  const TokenEvent('(Big Book, p. 63).'),
  _ev({'sources': [{'source': 'Alcoholics Anonymous - AA.pdf', 'similarity': 0, 'url': '/api/documents/x.pdf#b1', 'excerpt': 'God, I offer myself', 'doc_id': 'alcoholics-anonymous', 'block_ids': ['b1'], 'page': 63}]}),
  _ev({'research': {'type': 'verification', 'quotes': 2, 'quotes_verified': 2, 'pages': 1, 'pages_verified': 1}}),
  const DoneEvent(),
];

Future<(ProviderContainer, _ScriptedRepo)> _harness(List<ChatEvent> script) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final repo = _ScriptedRepo(script);
  final container = ProviderContainer(overrides: [
    sharedPreferencesProvider.overrideWithValue(prefs),
    chatRepositoryProvider.overrideWithValue(repo),
    distillerProvider.overrideWithValue(_NoDistill()),
  ]);
  addTearDown(container.dispose);
  return (container, repo);
}

void main() {
  test('research events parse into ResearchEvent; unknown keys are ignored', () {
    final e = ChatEvent.fromJson({'research': {'type': 'step', 'id': 3}});
    expect(e, isA<ResearchEvent>());
    expect((e as ResearchEvent).type, 'step');
    expect(ChatEvent.fromJson({'something_new': 1}), isNull);
  });

  test('research events fold into the message: steps, phase and the check', () async {
    final (c, _) = await _harness(_researchScript);
    await c.read(chatNotifierProvider.notifier).sendMessage('How many prayers are in each chapter?');
    final m = c.read(chatNotifierProvider).messages.last;
    expect(m.isResearch, isTrue);
    expect(m.researchSteps.map((s) => s.id), [1, 2], reason: 'steps upsert by id');
    expect(m.researchSteps.first.status, 'done');
    expect(m.researchSteps.first.detail, '3,679 words');
    expect(m.researchSteps.last.done, 4);
    expect(m.researchSteps.last.total, 11);
    expect(m.researchPhase, 'writing');
    expect(m.text, 'The Third Step prayer (Big Book, p. 63).');
    expect(m.sources.single.page, 63);
    expect(m.researchCheck!.allVerified, isTrue);

    // Survives a save/load round trip.
    final back = ChatMessage.fromJson(m.toJson());
    expect(back.isResearch, isTrue);
    expect(back.researchSteps.length, 2);
    expect(back.researchCheck!.quotes, 2);
  });

  test('a plain reply (no research events) stays an ordinary message', () async {
    final (c, _) = await _harness([const TokenEvent('Hi — good to see you.'), const DoneEvent()]);
    await c.read(chatNotifierProvider.notifier).sendMessage('hi');
    final m = c.read(chatNotifierProvider).messages.last;
    expect(m.isResearch, isFalse);
    expect(m.toHistoryJson()['content'], 'Hi — good to see you.');
  });

  test('the next turn carries research notes in its history', () async {
    final (c, repo) = await _harness(_researchScript);
    final n = c.read(chatNotifierProvider.notifier);
    await n.sendMessage('Prayers in How It Works?');
    await n.sendMessage('And in Into Action?');
    final prior = repo.lastHistory!.last.toHistoryJson()['content']!;
    expect(prior, contains('[Research notes: Reading “How It Works”'));
    expect(prior, isNot(contains('Reading 11 sections')), reason: 'only finished steps');
  });

  test('ConceptMap parses the compact node rows', () {
    final m = ConceptMap.fromJson({
      'fields': ['id', 'label', 'type', 'group', 'x', 'y', 'prominence', 'passages', 'top_peers'],
      'nodes': [
        ['t:resentment', 'Resentment', 'topic', 'struggles', 0.2, 0.3, 0.9, 1198, [1]],
        ['c:bill-wilson', 'Bill Wilson', 'person', 'recovery', 0.6, 0.1, 0.4, 300, [0]],
      ],
      'groups': [{'id': 'struggles', 'label': 'Struggles & Defects'}],
      'stats': {'passages': 40309, 'books': 97, 'chapters': 5080},
    });
    expect(m.nodes.length, 2);
    expect(m.byId('c:bill-wilson')!.type, 'person');
    expect(m.nodes.first.isTopic, isTrue);
    expect(m.nodes.first.topPeers, [1]);
    expect(m.passages, 40309);
  });
}
