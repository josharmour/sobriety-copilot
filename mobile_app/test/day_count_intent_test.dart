// Unit tests for queryWantsDayCount — the gate that decides when the local
// sobriety day count is shared with the assistant.
//
// The point of the gate is to STOP the model reciting the day count on every
// turn. So the false-positive cases (ordinary messages that merely contain
// "day"/"clean"/"sober") matter at least as much as the true positives.

import 'package:flutter_test/flutter_test.dart';
import 'package:sobriety_copilot_mobile/features/milestones/day_count_intent.dart';

void main() {
  group('queryWantsDayCount — should SHARE (about their own time)', () {
    const yes = <String>[
      'How long have I been sober?',
      'how many days do I have?',
      'How am I doing?',
      'What is my day count?',
      "what's my streak?",
      'how far along am I in recovery',
      "how's my progress?",
      'When is my sober anniversary?',
      'is there a milestone coming up soon',
      'I have 90 days today',
      "I'm at 6 months clean",
      'I just hit 30 days',
      'I reached 1 year',
      'tell me about my sobriety',
      'days sober — what should I know about the next one',
    ];
    for (final q in yes) {
      test('"$q"', () => expect(queryWantsDayCount(q), isTrue));
    }
  });

  group('queryWantsDayCount — should NOT share (bare words / off-topic)', () {
    const no = <String>[
      'How do I get through the day?',
      'I want to clean up my life',
      'How do I stay sober at parties?',
      'What does the literature say about sobriety?',
      "it's been a rough day",
      'how long does a meeting last?',
      'what should I clean first when I get home',
      'my sponsor is not answering',
      'help me with step 4',
      'I feel like drinking today',
      'what is a dry drunk',
      'how do I make amends',
      'tell me about acceptance',
      '',
    ];
    for (final q in no) {
      test('"$q"', () => expect(queryWantsDayCount(q), isFalse));
    }
  });
}
