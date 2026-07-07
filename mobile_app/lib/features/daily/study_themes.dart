import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/providers.dart';

/// Privacy-preserving "continue your study" suggestions.
///
/// Recent user messages (already stored locally in conversation history) are
/// matched against a hand-built recovery taxonomy — plain keyword scoring, no
/// model, no network. Opt-in via settings; nothing derived here ever leaves
/// the device.
class StudyTheme {
  final String id;
  final String label;
  final List<String> keywords;
  final List<String> prompts;

  const StudyTheme({
    required this.id,
    required this.label,
    required this.keywords,
    required this.prompts,
  });
}

const List<StudyTheme> kStudyThemes = [
  StudyTheme(
    id: 'resentment',
    label: 'Resentment',
    keywords: ['resent', 'angry', 'anger', 'furious', 'bitter', 'grudge', 'unfair', 'hate'],
    prompts: [
      'What does the Big Book say is the root of our troubles, and how do I work through a resentment?',
      'Walk me through the resentment inventory from the fourth step.',
    ],
  ),
  StudyTheme(
    id: 'fear',
    label: 'Fear',
    keywords: ['fear', 'afraid', 'scared', 'anxious', 'anxiety', 'worry', 'worried', 'panic'],
    prompts: [
      'How does the Big Book suggest we face and outgrow fear?',
      'What is the fear inventory and how do I do one?',
    ],
  ),
  StudyTheme(
    id: 'cravings',
    label: 'Cravings & triggers',
    keywords: ['craving', 'urge', 'tempted', 'temptation', 'trigger', 'relapse', 'drink', 'using', 'slip'],
    prompts: [
      'What does the literature say about the mental obsession and how the craving works?',
      'What practical actions do the first 164 pages suggest when the urge to drink comes?',
    ],
  ),
  StudyTheme(
    id: 'surrender',
    label: 'Steps 1–3',
    keywords: ['powerless', 'unmanageable', 'step 1', 'step one', 'step 2', 'step two', 'step 3', 'step three', 'surrender', 'higher power', 'god', 'turn it over', 'let go'],
    prompts: [
      'Help me study the first three steps — what does each actually ask of me?',
      'What does "turned our will and our lives over" mean in practice?',
    ],
  ),
  StudyTheme(
    id: 'inventory',
    label: 'Steps 4–5',
    keywords: ['step 4', 'step four', 'inventory', 'step 5', 'step five', 'moral inventory', 'admit', 'secrets', 'shame'],
    prompts: [
      'How do I actually write a fourth-step inventory, column by column?',
      'Why does the fifth step matter, and what should I expect from it?',
    ],
  ),
  StudyTheme(
    id: 'defects',
    label: 'Steps 6–7',
    keywords: ['step 6', 'step six', 'step 7', 'step seven', 'character defect', 'defects', 'shortcoming', 'humility', 'humble'],
    prompts: [
      'What is the difference between steps six and seven?',
      'What does the literature teach about humility and letting go of defects?',
    ],
  ),
  StudyTheme(
    id: 'amends',
    label: 'Steps 8–9',
    keywords: ['step 8', 'step eight', 'step 9', 'step nine', 'amends', 'apologize', 'apology', 'harmed', 'forgiveness', 'forgive'],
    prompts: [
      'How do I know when an amends would injure someone, and what do I do instead?',
      'Help me prepare for a difficult ninth-step amends.',
    ],
  ),
  StudyTheme(
    id: 'maintenance',
    label: 'Steps 10–11',
    keywords: ['step 10', 'step ten', 'step 11', 'step eleven', 'daily inventory', 'meditation', 'prayer', 'spot check', 'nightly review'],
    prompts: [
      'What does a real tenth-step practice look like day to day?',
      'How does the Big Book describe morning meditation and evening review?',
    ],
  ),
  StudyTheme(
    id: 'service',
    label: 'Step 12 & service',
    keywords: ['step 12', 'step twelve', 'service', 'carry the message', 'sponsee', 'newcomer', 'twelfth step call', 'help others'],
    prompts: [
      'What does "practicing these principles in all our affairs" mean?',
      'How did early members do twelfth-step work, and what can I copy today?',
    ],
  ),
  StudyTheme(
    id: 'sponsorship',
    label: 'Sponsorship',
    keywords: ['sponsor', 'sponsee', 'sponsorship', 'accountability'],
    prompts: [
      'What does the literature say about choosing and working with a sponsor?',
      'How do I get the most out of the sponsor relationship?',
    ],
  ),
  StudyTheme(
    id: 'relationships',
    label: 'Family & relationships',
    keywords: ['wife', 'husband', 'spouse', 'partner', 'marriage', 'family', 'kids', 'children', 'parents', 'divorce', 'relationship'],
    prompts: [
      'What guidance do the family chapters of the Big Book offer for rebuilding trust at home?',
      'How does recovery change our closest relationships, according to the literature?',
    ],
  ),
  StudyTheme(
    id: 'spirituality',
    label: 'Spiritual growth',
    keywords: ['spiritual', 'spirituality', 'faith', 'agnostic', 'atheist', 'believe', 'belief', 'awakening', 'conscious contact'],
    prompts: [
      'Help me study "We Agnostics" — what is it really arguing?',
      'What is a spiritual awakening as the literature describes it?',
    ],
  ),
  StudyTheme(
    id: 'gratitude',
    label: 'Gratitude',
    keywords: ['grateful', 'gratitude', 'thankful', 'blessing'],
    prompts: [
      'What role does gratitude play in staying sober, according to the literature?',
    ],
  ),
];

/// A ready-to-tap suggestion produced from local history.
class StudySuggestion {
  final String themeLabel;
  final String prompt;
  const StudySuggestion(this.themeLabel, this.prompt);
}

/// Scores [kStudyThemes] against the most recent user messages and returns up
/// to [maxSuggestions] prompts for the strongest themes (min 2 keyword hits).
/// The prompt within a theme rotates by day so the card changes over time
/// without shuffling on every rebuild.
List<StudySuggestion> suggestStudyThemes(
  Iterable<String> recentUserMessages, {
  int maxSuggestions = 2,
}) {
  final text = recentUserMessages.join(' \n ').toLowerCase();
  if (text.trim().isEmpty) return const [];

  final scores = <StudyTheme, int>{};
  for (final theme in kStudyThemes) {
    var score = 0;
    for (final kw in theme.keywords) {
      // Cheap word-ish boundary: keyword not immediately inside a longer word.
      var idx = text.indexOf(kw);
      while (idx >= 0) {
        final beforeOk = idx == 0 || !_isLetter(text.codeUnitAt(idx - 1));
        if (beforeOk) score++;
        idx = text.indexOf(kw, idx + kw.length);
      }
    }
    if (score >= 2) scores[theme] = score;
  }
  if (scores.isEmpty) return const [];

  final ranked = scores.keys.toList()
    ..sort((a, b) => scores[b]!.compareTo(scores[a]!));
  final dayIndex =
      DateTime.now().difference(DateTime(2026)).inDays; // stable within a day

  return [
    for (final theme in ranked.take(maxSuggestions))
      StudySuggestion(
        theme.label,
        theme.prompts[dayIndex % theme.prompts.length],
      ),
  ];
}

bool _isLetter(int codeUnit) =>
    (codeUnit >= 0x61 && codeUnit <= 0x7A) ||
    (codeUnit >= 0x41 && codeUnit <= 0x5A);

/// Suggestions derived from the last ~60 locally-stored user messages.
/// Empty when the user hasn't opted in.
final studySuggestionsProvider = Provider<List<StudySuggestion>>((ref) {
  final enabled =
      ref.watch(appConfigProvider.select((c) => c.studySuggestions));
  if (!enabled) return const [];
  final conversations = ref.watch(conversationsProvider);
  final messages = <String>[];
  for (final convo in conversations) {
    for (final msg in convo.messages) {
      if (msg.role == 'user' && msg.text.trim().isNotEmpty) {
        messages.add(msg.text);
      }
    }
  }
  final recent = messages.length > 60
      ? messages.sublist(messages.length - 60)
      : messages;
  return suggestStudyThemes(recent);
});
