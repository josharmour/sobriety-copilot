import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/milestones/relapse_log.dart';
import 'package:sobriety_copilot_mobile/features/milestones/widget_sync.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// One recovery milestone (keytag/chip). [days] is the day count at which it
/// is earned; colors follow the common NA keytag sequence so they read as
/// familiar to the audience.
class Milestone {
  final int days;
  final String label;
  final Color color;
  const Milestone(this.days, this.label, this.color);
}

/// Ordered milestone table. Beyond the last entry, yearly milestones are
/// generated on the fly (see [SobrietyState.nextMilestone]).
const List<Milestone> kMilestones = [
  Milestone(1, '24 hours', Color(0xFFF5F5F5)), // white
  Milestone(7, '1 week', Color(0xFFB0BEC5)), // silver
  Milestone(14, '2 weeks', Color(0xFF90A4AE)),
  Milestone(30, '30 days', Color(0xFFF4A261)), // orange
  Milestone(60, '60 days', Color(0xFF66BB6A)), // green
  Milestone(90, '90 days', Color(0xFFE76F51)), // red
  Milestone(180, '6 months', Color(0xFF42A5F5)), // blue
  Milestone(270, '9 months', Color(0xFFFFEE58)), // yellow
  Milestone(365, '1 year', Color(0xFFE0F7FA)), // glow
  Milestone(545, '18 months', Color(0xFF9E9E9E)), // gray
  Milestone(730, '2 years', Color(0xFF424242)), // black
];

/// Milestone for an arbitrary yearly anniversary past the table.
Milestone _yearMilestone(int years) =>
    Milestone(years * 365, '$years years', const Color(0xFF424242));

/// Date-only helper: local calendar date with the time stripped.
DateTime _dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

/// UTC-normalized calendar date (same year/month/day as [d]). Calendar-day
/// differences are computed on these so a spring-forward DST transition does
/// not undercount a span by one hour's worth of days.
DateTime _utcDateOnly(DateTime d) => DateTime.utc(d.year, d.month, d.day);

/// Locally-stored recovery tracker state. Never sent to the server.
class SobrietyState {
  /// Local calendar date of the first sober day, or null when not tracking.
  final DateTime? sobrietyDate;

  /// Discreet mode: show "Day 92" with no recovery wording (shoulder-surfing
  /// safety, mirrored by the home-screen widget).
  final bool discreet;

  /// Estimated daily spend (whole cents) for the money-saved card; null = off.
  final int? dailySpendCents;

  /// Relapse history, oldest first. Never deleted implicitly; the explicit
  /// "Erase relapse history" control is the only way to remove it. Each event
  /// carries the run length it reset in [RelapseEvent.lostDays].
  final List<RelapseEvent> relapses;

  /// Longest-run record preserved across an "Erase relapse history": erasing
  /// the events must never silently destroy the user's all-time best streak.
  final int bestStreakDays;

  const SobrietyState({
    this.sobrietyDate,
    this.discreet = false,
    this.dailySpendCents,
    this.relapses = const [],
    this.bestStreakDays = 0,
  });

  bool get isTracking => sobrietyDate != null;

  /// Total number of logged relapses.
  int get totalRelapses => relapses.length;

  /// Longest continuous sober run on record. When no relapse has been logged
  /// this equals the current run ([daysSober]); once relapses exist, each
  /// event's [RelapseEvent.lostDays] preserves the run it reset, and the best
  /// of those (plus the current run) is the all-time best. NaN-proof: 0 when
  /// untracked.
  int get longestStreak => longestStreakAt(DateTime.now());

  /// Same as [longestStreak] but for a supplied "now" (see [daysSoberAt]),
  /// so tests can pin the history-vs-current-run behavior deterministically.
  int longestStreakAt(DateTime now) {
    var best = daysSoberAt(now); // current run
    if (bestStreakDays > best) best = bestStreakDays; // survives erased history
    for (final r in relapses) {
      if (r.lostDays > best) best = r.lostDays;
    }
    return best;
  }

  /// Completed days since the sobriety date (0 on the date itself), computed
  /// on local calendar days so it advances exactly at midnight. Differences
  /// are taken on UTC-normalized dates so DST spring-forward does not
  /// undercount.
  int get daysSober => daysSoberAt(DateTime.now());

  /// Same as [daysSober] but for a supplied "now", so tests can pin DST,
  /// timezone, and midnight behavior against a fixed instant instead of the
  /// wall clock.
  int daysSoberAt(DateTime now) {
    final d = sobrietyDate;
    if (d == null) return 0;
    final diff = _utcDateOnly(now).difference(_utcDateOnly(d)).inDays;
    return diff < 0 ? 0 : diff;
  }

  /// Most recently earned milestone, or null before day 1.
  Milestone? get lastMilestone {
    final days = daysSober;
    Milestone? last;
    for (final m in kMilestones) {
      if (days >= m.days) last = m;
    }
    if (last != null && last.days == kMilestones.last.days) {
      final years = days ~/ 365;
      if (years >= 2) return _yearMilestone(years);
    }
    return last;
  }

  /// Next milestone to reach; yearly anniversaries after the table runs out.
  Milestone get nextMilestone {
    final days = daysSober;
    for (final m in kMilestones) {
      if (days < m.days) return m;
    }
    final nextYears = (days ~/ 365) + 1;
    return _yearMilestone(nextYears);
  }

  /// Progress (0..1) from the previous milestone toward [nextMilestone].
  double get milestoneProgress {
    final days = daysSober;
    final next = nextMilestone;
    var prev = 0;
    for (final m in kMilestones) {
      if (m.days < next.days && m.days > prev) prev = m.days;
    }
    if (next.days > kMilestones.last.days) {
      prev = next.days - 365;
    }
    final span = next.days - prev;
    if (span <= 0) return 0;
    return ((days - prev) / span).clamp(0.0, 1.0);
  }

  double? get moneySaved {
    final cents = dailySpendCents;
    if (cents == null || cents <= 0) return null;
    return daysSober * cents / 100.0;
  }

  SobrietyState copyWith({
    DateTime? sobrietyDate,
    bool clearDate = false,
    bool? discreet,
    int? dailySpendCents,
    bool clearSpend = false,
    List<RelapseEvent>? relapses,
    int? bestStreakDays,
  }) {
    return SobrietyState(
      sobrietyDate: clearDate ? null : (sobrietyDate ?? this.sobrietyDate),
      discreet: discreet ?? this.discreet,
      dailySpendCents:
          clearSpend ? null : (dailySpendCents ?? this.dailySpendCents),
      relapses: relapses ?? this.relapses,
      bestStreakDays: bestStreakDays ?? this.bestStreakDays,
    );
  }

  factory SobrietyState.fromJson(Map<String, dynamic> json) {
    DateTime? date;
    final raw = json['sobrietyDate'];
    if (raw is String && raw.isNotEmpty) {
      date = DateTime.tryParse(raw);
    }
    final spend = json['dailySpendCents'];
    final rawRelapses = json['relapses'];
    final relapses = rawRelapses is List
        ? rawRelapses
            .whereType<Map>()
            .map((m) => RelapseEvent.fromJson(Map<String, dynamic>.from(m)))
            .toList()
        : <RelapseEvent>[];
    final best = json['bestStreakDays'];
    return SobrietyState(
      sobrietyDate: date == null ? null : _dateOnly(date),
      discreet: json['discreet'] as bool? ?? false,
      dailySpendCents: spend is int && spend > 0 ? spend : null,
      relapses: relapses,
      bestStreakDays: best is int && best > 0 ? best : 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'sobrietyDate': sobrietyDate == null
            ? null
            : '${sobrietyDate!.year.toString().padLeft(4, '0')}-'
                '${sobrietyDate!.month.toString().padLeft(2, '0')}-'
                '${sobrietyDate!.day.toString().padLeft(2, '0')}',
        'discreet': discreet,
        'dailySpendCents': dailySpendCents,
        'relapses': relapses.map((e) => e.toJson()).toList(),
        'bestStreakDays': bestStreakDays,
      };

  static const String prefsKey = 'sobriety_tracker_v1';
}

/// Owns the persisted [SobrietyState] and mirrors changes to the home-screen
/// widget bridge (a no-op on surfaces without widgets).
class SobrietyNotifier extends Notifier<SobrietyState> {
  @override
  SobrietyState build() {
    final raw = ref.read(sharedPreferencesProvider).getString(
          SobrietyState.prefsKey,
        );
    if (raw == null || raw.isEmpty) return const SobrietyState();
    try {
      final state =
          SobrietyState.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      // Keep the widget fresh across app restarts even if nothing changes.
      _sync(state);
      return state;
    } catch (_) {
      return const SobrietyState();
    }
  }

  Future<void> _sync(SobrietyState s) {
    final json = s.toJson();
    return syncSobrietyWidget(
      dateIso: json['sobrietyDate'] as String?,
      discreet: s.discreet,
    );
  }

  Future<void> setDate(DateTime date) async {
    state = state.copyWith(sobrietyDate: _dateOnly(date));
    await _persist();
  }

  Future<void> clearDate() async {
    state = state.copyWith(clearDate: true);
    await _persist();
  }

  Future<void> setDiscreet(bool value) async {
    state = state.copyWith(discreet: value);
    await _persist();
  }

  Future<void> setDailySpend(double? dollars) async {
    if (dollars == null || dollars <= 0) {
      state = state.copyWith(clearSpend: true);
    } else {
      state = state.copyWith(dailySpendCents: (dollars * 100).round());
    }
    await _persist();
  }

  /// Logs a relapse: records the event with the run length it reset, then
  /// restarts the day counter from today — never deleting history. Shame-free
  /// by design; the best/longest streak is preserved in the event log.
  Future<void> logRelapse({String note = '', String trigger = ''}) async {
    // Capture one instant so the event date, the lost-days count, and the
    // reset date can never straddle a midnight and disagree.
    final now = _dateOnly(DateTime.now());
    final lost = state.daysSoberAt(now);
    final event = RelapseEvent(
      date: now,
      note: note,
      trigger: trigger,
      lostDays: lost,
    );
    state = state.copyWith(
      sobrietyDate: now,
      relapses: [...state.relapses, event],
    );
    // TODO(fr5): reset check-in streak
    await _persist();
  }

  /// Permanently removes all logged relapse events (dates, notes, triggers)
  /// and the history they carry. Used by the explicit "Erase relapse history"
  /// control — the only way to delete this sensitive history from the device.
  /// The all-time longest-streak record is preserved (as a bare number, no
  /// event data) so erasing private notes never destroys an achievement.
  /// [now] is a test seam; production callers omit it.
  Future<void> clearRelapses({DateTime? now}) async {
    final preserved = state.longestStreakAt(now ?? DateTime.now());
    state = state.copyWith(relapses: const [], bestStreakDays: preserved);
    await _persist();
  }

  /// Erases the preserved longest-streak record (set by [clearRelapses]).
  /// Completes the in-app deletion story: with history erased, tracking
  /// stopped, and the record cleared, no recovery data remains on disk. Also
  /// the only way to correct a record inflated by a mis-set sobriety date.
  Future<void> clearBestStreak() async {
    state = state.copyWith(bestStreakDays: 0);
    await _persist();
  }

  Future<void> _persist() async {
    await ref.read(sharedPreferencesProvider).setString(
          SobrietyState.prefsKey,
          jsonEncode(state.toJson()),
        );
    await _sync(state);
  }
}

final sobrietyProvider =
    NotifierProvider<SobrietyNotifier, SobrietyState>(SobrietyNotifier.new);
