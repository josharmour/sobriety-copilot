import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/starter_prompts.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test('Dynamic topic catalog has 92 recovery topics and 1,700+ unique prompts', () {
    expect(kRecoveryTopicCatalog.length, 92);
    expect(kAllStarterPrompts.length, greaterThan(1700));
    for (final topic in kRecoveryTopicCatalog) {
      expect(topic.prompts, isNotEmpty, reason: 'Topic ${topic.id} has no prompts');
      expect(topic.keywords, isNotEmpty, reason: 'Topic ${topic.id} has no keywords');
      expect(topic.peerTopicIds, isNotEmpty, reason: 'Topic ${topic.id} has no peers');
    }
  });

  test('Single-turn preloaded starter click ("testing the app") produces 0 interest signal', () async {
    final prefs = await SharedPreferences.getInstance();
    final starterText = kStarterPrompts['day']!.first;
    expect(isKnownStarterPrompt(starterText), isTrue);

    final unengagedStarterConv = Conversation(
      id: 'conv_test_click',
      title: starterText,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [
        ChatMessage.user(starterText),
        ChatMessage(
          id: 'a1',
          role: 'assistant',
          text: 'Here is what the Big Book says...',
          createdAt: DateTime.now(),
        ),
      ],
    );

    final signals = extractTrueInterestSignals(
      conversations: [unengagedStarterConv],
      prefs: prefs,
    );
    expect(signals, isEmpty);

    final scores = extractTrueInterestTopicScores(
      conversations: [unengagedStarterConv],
      prefs: prefs,
    );
    expect(scores, isEmpty);
  });

  test('User-typed query produces strong topic and peer-topic interest scores', () async {
    final prefs = await SharedPreferences.getInstance();
    const typedQuery =
        'I am struggling with deep resentment and anger toward my coworker at my job';
    expect(isKnownStarterPrompt(typedQuery), isFalse);

    final typedConv = Conversation(
      id: 'conv_typed',
      title: typedQuery,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [
        ChatMessage.user(typedQuery),
        ChatMessage(
          id: 'a1',
          role: 'assistant',
          text: 'Resentment is the number one offender...',
          createdAt: DateTime.now(),
        ),
      ],
    );

    final scores = extractTrueInterestTopicScores(
      conversations: [typedConv],
      prefs: prefs,
    );
    expect(scores, isNotEmpty);
    expect(scores['resentment'], isNotNull);
    expect(scores['anger'], isNotNull);
    expect(scores['work'], isNotNull);
  });

  test('Starter prompt followed by a second user turn or saved memory counts as true interest', () async {
    final prefs = await SharedPreferences.getInstance();
    const starterText = 'What does the Big Book say about resentment?';
    await recordStarterPromptTapped(prefs, starterText);

    // 1. Multi-turn follow-up after starter tap -> included!
    final engagedConv = Conversation(
      id: 'conv_engaged',
      title: starterText,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [
        ChatMessage.user(starterText),
        ChatMessage(
          id: 'a1',
          role: 'assistant',
          text: 'Page 64 explains resentment...',
          createdAt: DateTime.now(),
        ),
        ChatMessage.user('How do I write out the fourth column for that person?'),
      ],
    );

    final signalsMultiTurn = extractTrueInterestSignals(
      conversations: [engagedConv],
      prefs: prefs,
    );
    expect(signalsMultiTurn.length, 2);

    // 2. Single-turn starter tap where the user saved a memory fact -> included!
    final singleTurnWithMemory = Conversation(
      id: 'conv_mem',
      title: starterText,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      messages: [
        ChatMessage.user(starterText),
        ChatMessage(
          id: 'a2',
          role: 'assistant',
          text: 'Page 64 explains resentment...',
          createdAt: DateTime.now(),
        ),
      ],
    );
    final memory = PersonalMemory(
      facts: [
        MemoryFact(
          id: 'f1',
          text: 'Working on resentment inventory',
          createdAt: DateTime.now(),
          sourceConversationId: 'conv_mem',
        ),
      ],
    );

    final signalsWithMemory = extractTrueInterestSignals(
      conversations: [singleTurnWithMemory],
      memory: memory,
      prefs: prefs,
    );
    expect(signalsWithMemory, isNotEmpty);
  });

  test('pickStarterPrompts blends true-interest topics with discovery and avoids repeats', () async {
    final prefs = await SharedPreferences.getInstance();
    final scores = <String, double>{
      'resentment': 12.0,
      'step_4': 9.5,
      'forgiveness': 7.0,
    };

    final hand1 = pickStarterPrompts(
      prefs,
      count: 5,
      random: Random(42),
      topicScores: scores,
    );
    expect(hand1.length, 5);
    expect(hand1.toSet().length, 5);

    // At least 2 prompts in hand1 should come from the top-scored topics
    final topTopicPrompts = <String>{
      ...kTopicById['resentment']!.prompts,
      ...kTopicById['step_4']!.prompts,
      ...kTopicById['forgiveness']!.prompts,
    };
    final matchedTop = hand1.where(topTopicPrompts.contains).length;
    expect(matchedTop, greaterThanOrEqualTo(2));

    // Next hand should not repeat anything from hand1
    final hand2 = pickStarterPrompts(
      prefs,
      count: 5,
      random: Random(43),
      topicScores: scores,
    );
    expect(hand2.length, 5);
    expect(hand2.toSet().intersection(hand1.toSet()), isEmpty);
  });
}
