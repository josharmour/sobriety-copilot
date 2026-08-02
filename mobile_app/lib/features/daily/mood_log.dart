import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/daily/inventory.dart'
    show dateIsoOf;
import 'package:sobriety_copilot_mobile/providers.dart';

/// Mood scale bounds. 1 = low, 5 = high.
const int kMoodMin = 1;
const int kMoodMax = 5;

/// Curated, recovery-relevant, non-clinical emotion labels (mirrors
/// SoberTool's selector, pruned). Single source of truth for the check-in
/// selector and the trend-view coloring.
const List<String> kMoodEmotions = [
  'Grateful',
  'Peaceful',
  'Hopeful',
  'Content',
  'Calm',
  'Okay',
  'Restless',
  'Anxious',
  'Sad',
  'Angry',
  'Ashamed',
  'Alone',
  'Hopeless',
];

/// Maps each emotion label to a 1–5 mood value. Positive ≈ 4–5, neutral ≈ 3,
/// negative ≈ 1–2. Single source of truth for the selector and history colors.
const Map<String, int> kEmotionMood = {
  'Grateful': 5,
  'Peaceful': 5,
  'Hopeful': 4,
  'Content': 4,
  'Calm': 4,
  'Okay': 3,
  'Restless': 2,
  'Anxious': 2,
  'Sad': 2,
  'Angry': 1,
  'Ashamed': 1,
  'Alone': 1,
  'Hopeless': 1,
};

/// A single day's mood check-in (one per local calendar date, keyed by
/// `dateIso` via [dateIsoOf]). Journal text and label are optional.
///
/// Local-only. Never leaves the device.
class MoodEntry {
  final String dateIso; // yyyy-MM-dd, local — via dateIsoOf
  final int mood; // 1..5
  final String label; // optional emotion label (may be empty)
  final String journal; // optional free text (may be empty)

  const MoodEntry({
    required this.dateIso,
    required this.mood,
    this.label = '',
    this.journal = '',
  });

  factory MoodEntry.fromJson(Map<String, dynamic> json) => MoodEntry(
        dateIso: (json['date'] as String?) ?? '',
        mood: ((json['mood'] as num?)?.toInt() ?? 3).clamp(kMoodMin, kMoodMax),
        label: (json['label'] as String?) ?? '',
        journal: (json['journal'] as String?) ?? '',
      );

  Map<String, dynamic> toJson() => {
        'date': dateIso,
        'mood': mood,
        'label': label,
        'journal': journal,
      };

  /// Plain-text share of a single entry (explicit sponsor share only).
  String toShareText() {
    final b = StringBuffer('$label — $dateIso\n');
    b.writeln('Mood $mood/5');
    final j = journal.trim();
    if (j.isNotEmpty) b.writeln(j);
    return b.toString();
  }
}

/// Persisted mood log: one [MoodEntry] per day, newest-first, capped at
/// ~[_kMaxMoodEntries] (oldest beyond the cap are dropped). Local-only
/// (SharedPreferences) — never reaches the server.
class MoodNotifier extends Notifier<List<MoodEntry>> {
  static const String prefsKey = 'mood_log_v1';

  /// ~2 years of daily entries (365 * 2 = 730).
  static const int _kMaxMoodEntries = 730;

  @override
  List<MoodEntry> build() {
    final raw = ref.read(sharedPreferencesProvider).getString(prefsKey);
    if (raw == null || raw.isEmpty) return const [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return const [];
      return _normalize(
        decoded.whereType<Map>().map(
          (m) => MoodEntry.fromJson(Map<String, dynamic>.from(m)),
        ),
      );
    } catch (_) {
      return const [];
    }
  }

  /// The farthest-back dateIso we retain (two years ago today).
  String _oldestKept() =>
      dateIsoOf(DateTime.now().subtract(const Duration(days: 730)));

  /// Prunes entries older than two years and enforces the cap, newest-first.
  List<MoodEntry> _normalize(Iterable<MoodEntry> entries) {
    final oldest = _oldestKept();
    final kept = entries.where((e) => e.dateIso.compareTo(oldest) >= 0).toList();
    kept.sort((a, b) => b.dateIso.compareTo(a.dateIso));
    if (kept.length > _kMaxMoodEntries) {
      kept.removeRange(_kMaxMoodEntries, kept.length);
    }
    return kept;
  }

  /// The entry for [date], compared by local calendar date only (never raw
  /// [DateTime] equality). Null when there is no entry for that day.
  MoodEntry? entryFor(DateTime date) {
    final iso = dateIsoOf(date);
    for (final e in state) {
      if (e.dateIso == iso) return e;
    }
    return null;
  }

  /// Inserts [entry] replacing any existing same-day entry, keeping the list
  /// sorted newest-first and within storage bounds.
  Future<void> upsert(MoodEntry entry) async {
    final next =
        state.where((e) => e.dateIso != entry.dateIso).toList();
    next.insert(0, entry);
    state = _normalize(next);
    await _persist();
  }

  Future<void> _persist() async {
    await ref
        .read(sharedPreferencesProvider)
        .setString(prefsKey, jsonEncode(state.map((e) => e.toJson()).toList()));
  }
}
