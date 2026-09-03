/// Relapse event model + persistence.
///
/// One value type capturing a single logged relapse: the calendar date, an
/// optional free-text note, an optional trigger tag, and the running streak
/// length (in completed sober days) that this relapse reset.
library;

/// A single logged relapse. The streak lost by this event lives in
/// [lostDays]; the history is never deleted, so old run lengths survive
/// resets and feed the `longestStreak` stat.
class RelapseEvent {
  /// Local calendar date of the relapse (time stripped).
  final DateTime date;

  /// Optional free-text note (may be empty).
  final String note;

  /// Optional trigger tag (may be empty).
  final String trigger;

  /// Running streak length (completed sober days) lost by this relapse.
  final int lostDays;

  const RelapseEvent({
    required this.date,
    this.note = '',
    this.trigger = '',
    required this.lostDays,
  });

  Map<String, dynamic> toJson() => {
        'date': _dateOnlyIso(date),
        'note': note,
        'trigger': trigger,
        'lostDays': lostDays,
      };

  factory RelapseEvent.fromJson(Map<String, dynamic> json) {
    final raw = json['date'] as String?;
    return RelapseEvent(
      date: DateTime.tryParse(raw ?? '') ?? DateTime.now(),
      note: json['note'] as String? ?? '',
      trigger: json['trigger'] as String? ?? '',
      lostDays: json['lostDays'] as int? ?? 0,
    );
  }
}

/// Date-only ISO serialization (`yyyy-MM-dd`, local calendar day), matching
/// the format used by `SobrietyState.toJson`.
String _dateOnlyIso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';
