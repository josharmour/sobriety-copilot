import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/providers.dart';

/// One yes/no question in the nightly review. [unfavorableWhenYes] marks the
/// answers that invite a follow-up note (resentful? → yes is the flag;
/// kind and loving? → no is the flag).
class InventoryQuestion {
  final String id;
  final String text;
  final bool unfavorableWhenYes;
  const InventoryQuestion(this.id, this.text, {this.unfavorableWhenYes = true});
}

/// The Big Book's nightly-review questions (1st ed., Into Action), lightly
/// split into single yes/no items. "What could we have done better?" is the
/// free-text prompt below rather than a toggle.
const List<InventoryQuestion> kInventoryQuestions = [
  InventoryQuestion('resentful', 'Was I resentful today?'),
  InventoryQuestion('selfish', 'Was I selfish?'),
  InventoryQuestion('dishonest', 'Was I dishonest?'),
  InventoryQuestion('afraid', 'Was I afraid?'),
  InventoryQuestion('apology', 'Do I owe anyone an apology?'),
  InventoryQuestion(
    'secret',
    'Am I keeping something to myself that should be discussed with another person?',
  ),
  InventoryQuestion(
    'kind',
    'Was I kind and loving toward all?',
    unfavorableWhenYes: false,
  ),
  InventoryQuestion(
    'service',
    'Did I think of what I could do for others?',
    unfavorableWhenYes: false,
  ),
];

const String kInventoryFreeTextPrompt = 'What could I have done better?';

/// A saved nightly check-in for one local calendar date.
class InventoryEntry {
  final String dateIso; // yyyy-MM-dd, local
  final Map<String, bool> answers; // question id -> answer
  final Map<String, String> notes; // question id -> follow-up note
  final String reflection; // "what could I have done better"
  final List<String> gratitude;

  const InventoryEntry({
    required this.dateIso,
    required this.answers,
    required this.notes,
    required this.reflection,
    required this.gratitude,
  });

  factory InventoryEntry.fromJson(Map<String, dynamic> json) => InventoryEntry(
        dateIso: (json['date'] as String?) ?? '',
        answers: ((json['answers'] as Map?) ?? {})
            .map((k, v) => MapEntry(k.toString(), v == true)),
        notes: ((json['notes'] as Map?) ?? {})
            .map((k, v) => MapEntry(k.toString(), v.toString())),
        reflection: (json['reflection'] as String?) ?? '',
        gratitude: ((json['gratitude'] as List?) ?? [])
            .map((e) => e.toString())
            .where((s) => s.isNotEmpty)
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'date': dateIso,
        'answers': answers,
        'notes': notes,
        'reflection': reflection,
        'gratitude': gratitude,
      };

  /// Plain-text export (share-to-sponsor). Discreet header on purpose.
  String toShareText() {
    final b = StringBuffer('Evening review — $dateIso\n');
    for (final q in kInventoryQuestions) {
      final a = answers[q.id];
      if (a == null) continue;
      b.writeln('- ${q.text} ${a ? 'Yes' : 'No'}');
      final note = notes[q.id];
      if (note != null && note.trim().isNotEmpty) {
        b.writeln('    ${note.trim()}');
      }
    }
    if (reflection.trim().isNotEmpty) {
      b.writeln('- $kInventoryFreeTextPrompt ${reflection.trim()}');
    }
    if (gratitude.isNotEmpty) {
      b.writeln('- Grateful for: ${gratitude.join(', ')}');
    }
    return b.toString();
  }
}

String dateIsoOf(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

/// All saved check-ins, keyed by dateIso. Local-only (SharedPreferences),
/// capped to the most recent 400 entries.
class InventoryNotifier extends Notifier<Map<String, InventoryEntry>> {
  static const String prefsKey = 'inventory_v1';
  static const int _cap = 400;

  @override
  Map<String, InventoryEntry> build() {
    final raw = ref.read(sharedPreferencesProvider).getString(prefsKey);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      return decoded.map(
        (k, v) => MapEntry(
          k,
          InventoryEntry.fromJson(v as Map<String, dynamic>),
        ),
      );
    } catch (_) {
      return {};
    }
  }

  InventoryEntry? entryFor(DateTime date) => state[dateIsoOf(date)];

  /// Saving tonight's review counts as the daily check-in (FR5); edits of
  /// past days do not.
  Future<void> save(InventoryEntry entry) async {
    final next = Map<String, InventoryEntry>.from(state);
    next[entry.dateIso] = entry;
    if (next.length > _cap) {
      final keys = next.keys.toList()..sort();
      for (final k in keys.take(next.length - _cap)) {
        next.remove(k);
      }
    }
    state = next;
    await _persist();
    // One captured instant so the today-guard and the recorded day can never
    // straddle midnight and disagree.
    final now = DateTime.now();
    if (entry.dateIso == dateIsoOf(now)) {
      await ref.read(streakProvider.notifier).recordCheckIn(now: now);
    }
  }

  Future<void> delete(String dateIso) async {
    final next = Map<String, InventoryEntry>.from(state)..remove(dateIso);
    state = next;
    await _persist();
  }

  /// Consecutive-day streak ending today (or yesterday, if tonight's review
  /// hasn't been done yet).
  int get streak {
    var day = DateTime.now();
    if (!state.containsKey(dateIsoOf(day))) {
      day = day.subtract(const Duration(days: 1));
    }
    var count = 0;
    while (state.containsKey(dateIsoOf(day))) {
      count++;
      day = day.subtract(const Duration(days: 1));
    }
    return count;
  }

  Future<void> _persist() async {
    await ref.read(sharedPreferencesProvider).setString(
          prefsKey,
          jsonEncode(state.map((k, v) => MapEntry(k, v.toJson()))),
        );
  }
}

final inventoryProvider =
    NotifierProvider<InventoryNotifier, Map<String, InventoryEntry>>(
  InventoryNotifier.new,
);
