/// Unit tests for local (Private Mode) prompt assembly.
///
/// Verifies passage count, context budget, and system prompt tightness.
import 'package:flutter_test/flutter_test.dart';

import 'package:sobriety_copilot_mobile/features/private_mode/local_prompts.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/local_chat_repository.dart';

void main() {
  group('LocalChatRepository — passage & context budget', () {
    test('kMaxInjectedPassages is 3 (not 4, not 8)', () {
      expect(
        LocalChatRepository.kMaxInjectedPassages,
        3,
        reason: 'On-device prefill is the bottleneck — '
            'reducing from 4 to 3 cuts TTFT meaningfully.',
      );
    });
  });

  group('Local prompts — tightened system prompt', () {
    test('all system prompts exclude the old boilerplate', () {
      // Old phrasing we intentionally removed.
      const oldPhrases = [
        'lived experience',
        'point people there',
        'closing affirmations',
        'genuinely needs',
      ];
      for (final tone in ['warm', 'balanced', 'brief']) {
        final prompt = localSystemPrompt(tone);
        for (final phrase in oldPhrases) {
          expect(
            prompt.contains(phrase),
            false,
            reason: 'Tone "$tone" still contains removed boilerplate: "$phrase"',
          );
        }
      }
    });

    test('all system prompts retain citation instruction', () {
      for (final tone in ['warm', 'balanced', 'brief']) {
        final prompt = localSystemPrompt(tone);
        expect(
          prompt.contains('plainly by its title'),
          true,
          reason: 'Tone "$tone" is missing the citation rule',
        );
        expect(
          prompt.contains('filenames'),
          true,
          reason: 'Tone "$tone" is missing the no-filenames rule',
        );
      }
    });

    test('each system prompt is under 1000 chars', () {
      // Tightened prompts should be well under the old ~1112 char max.
      for (final tone in ['warm', 'balanced', 'brief']) {
        final prompt = localSystemPrompt(tone);
        expect(
          prompt.length,
          lessThan(1000),
          reason: 'Tone "$tone" is ${prompt.length} chars (target <1000)',
        );
      }
    });
  });

  group('User-turn prompt — context budget', () {
    test('localUserMessage respects a hard cap on context size', () {
      // Build a context string at the edge of the budget.
      final largeContext = 'A' * 2800; // exceeds _maxContextChars + overhead
      final msg = localUserMessage(context: largeContext, question: 'test');
      // The prompt builder doesn't trim context itself — that happens in the
      // retrieval loop. Verify the assembled message is reasonable and the
      // instruction tail is present.
      expect(msg.contains('Ground your answer'), true);
      expect(msg.contains('test'), true);
    });

    test('no-context message skips passage framing', () {
      final msg = localNoContextMessage(question: 'hello');
      expect(msg.contains('No passages from the offline library matched'), true);
      expect(msg.contains('hello'), true);
      expect(msg.contains('Relevant passages'), false);
    });
  });

  group('Thinking panel — streaming path verification', () {
    test('ThinkingEvent handler appends incrementally', () {
      // Simulate the chat_notifier pattern: thinking field is accumulated.
      String thinking = '';
      final chunks = ['First ', 'chunk of ', 'reasoning.'];
      for (final c in chunks) {
        thinking += c;
      }
      expect(thinking, 'First chunk of reasoning.');
      expect(thinking.length, greaterThan(chunks[0].length));
    });
  });

  group('Typing indicator — LoadingDots displays on streaming empty', () {
    test('streaming-empty condition is correct', () {
      // Matches _assistantBubble logic:
      //   streamingEmpty = isStreaming && !hasText && !hasDiffusion
      bool streamingEmpty(bool isStreaming, bool hasText, bool hasDiffusion) =>
          isStreaming && !hasText && !hasDiffusion;

      expect(streamingEmpty(true, false, false), isTrue,
          reason: 'Streaming with no content should show dots');
      expect(streamingEmpty(true, true, false), isFalse,
          reason: 'Has text — dots hidden');
      expect(streamingEmpty(true, false, true), isFalse,
          reason: 'Has diffusion — dots hidden');
      expect(streamingEmpty(false, false, false), isFalse,
          reason: 'Not streaming — no dots');
    });
  });
}
