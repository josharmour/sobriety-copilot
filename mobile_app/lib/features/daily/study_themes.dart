import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/data/starter_prompts.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Privacy-preserving "continue your study" and dynamic starter topic scoring.
///
/// Recent user messages (already stored locally in conversation history) are
/// matched against the 92-topic / 2,500+ sub-concept recovery taxonomy — plain
/// on-device keyword & concept graph scoring, no network.
///
/// Crucial signal filter: single-turn clicks on preloaded starter prompts
/// ("testing the app") are ignored unless the user interacted further in that
/// conversation (follow-up turns, saved passages, or saved memory facts).
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

/// All 92 recovery topics exposed as [StudyTheme] entries for compatibility.
final List<StudyTheme> kStudyThemes = [
  for (final t in kRecoveryTopicCatalog)
    StudyTheme(
      id: t.id,
      label: t.label,
      keywords: t.keywords,
      prompts: t.prompts,
    ),
];

/// A ready-to-tap suggestion produced from local history.
class StudySuggestion {
  final String themeLabel;
  final String prompt;
  const StudySuggestion(this.themeLabel, this.prompt);
}

/// Scores [kStudyThemes] against the provided user messages and returns up
/// to [maxSuggestions] prompts for the strongest themes.
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

/// Live on-device topic interest scores derived ONLY from true interest
/// signals:
/// - Queries the user typed/dictated/scanned themselves
/// - Preloaded starter queries where the user continued interacting ($\ge 2$
///   user turns, or saved a passage/memory fact from that conversation)
/// - Personal memory facts, triggers, goals, and open threads (when memory is on)
final trueInterestTopicScoresProvider = Provider<Map<String, double>>((ref) {
  final conversations = ref.watch(conversationsProvider);
  final savedPassages = ref.watch(savedPassagesProvider);
  final memoryEnabled = ref.watch(memoryEnabledProvider);
  final memory = memoryEnabled ? ref.watch(personalMemoryProvider) : null;
  final prefs = ref.watch(sharedPreferencesProvider);

  return extractTrueInterestTopicScores(
    conversations: conversations,
    memory: memory,
    savedPassages: savedPassages,
    prefs: prefs,
  );
});

/// Suggestions derived from true-interest user messages across local history.
final studySuggestionsProvider = Provider<List<StudySuggestion>>((ref) {
  final conversations = ref.watch(conversationsProvider);
  final savedPassages = ref.watch(savedPassagesProvider);
  final memoryEnabled = ref.watch(memoryEnabledProvider);
  final memory = memoryEnabled ? ref.watch(personalMemoryProvider) : null;
  final prefs = ref.watch(sharedPreferencesProvider);

  final signals = extractTrueInterestSignals(
    conversations: conversations,
    memory: memory,
    savedPassages: savedPassages,
    prefs: prefs,
  );
  if (signals.isEmpty) return const [];

  final recentTexts = signals.length > 60
      ? signals.sublist(signals.length - 60).map((s) => s.text)
      : signals.map((s) => s.text);
  return suggestStudyThemes(recentTexts);
});
