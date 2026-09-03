import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../widgets/daily_widget_sync.dart';

/// One public-domain (or original) daily reading from assets/daily/readings.json.
class DailyReading {
  final String title;
  final String body;
  final String source;

  const DailyReading({
    required this.title,
    required this.body,
    required this.source,
  });

  factory DailyReading.fromJson(Map<String, dynamic> json) => DailyReading(
        title: (json['title'] as String?) ?? '',
        body: (json['body'] as String?) ?? '',
        source: (json['source'] as String?) ?? '',
      );
}

/// Parsed readings bundle: the rotating entries plus the fixed morning and
/// evening practice texts (Big Book 1st ed., Into Action).
class DailyReadingsBundle {
  final DailyReading morningPractice;
  final DailyReading eveningPractice;
  final List<DailyReading> entries;

  const DailyReadingsBundle({
    required this.morningPractice,
    required this.eveningPractice,
    required this.entries,
  });

  /// Deterministic reading for [date] — same for everyone all day.
  DailyReading forDate(DateTime date) {
    if (entries.isEmpty) return morningPractice;
    final startOfYear = DateTime(date.year);
    final dayOfYear = date.difference(startOfYear).inDays;
    return entries[dayOfYear % entries.length];
  }
}

final dailyReadingsProvider = FutureProvider<DailyReadingsBundle>((ref) async {
  final raw = await rootBundle.loadString('assets/daily/readings.json');
  final json = jsonDecode(raw) as Map<String, dynamic>;
  final entries = (json['entries'] as List)
      .whereType<Map<String, dynamic>>()
      .map(DailyReading.fromJson)
      .toList();
  final bundle = DailyReadingsBundle(
    morningPractice: DailyReading.fromJson(
      json['morning_practice'] as Map<String, dynamic>,
    ),
    eveningPractice: DailyReading.fromJson(
      json['evening_practice'] as Map<String, dynamic>,
    ),
    entries: entries,
  );

  // Sync today's reading to home-screen widgets in background
  DailyWidgetSync.syncTodayReading(bundle).ignore();

  return bundle;
});
