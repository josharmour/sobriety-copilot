/// FR5 — daily check-in streak: consecutive days the user showed up for
/// themselves (evening review, mood check-in, a completed meditation, or an
/// explicit "Check in" tap). This is the single user-facing streak, distinct
/// from the FR1 sobriety metric (days sober) — it counts engagement days.
///
/// Local only. Never sent to the server.
library;

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/providers.dart';

/// Local calendar date with the time stripped.
DateTime _dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

/// UTC-normalized calendar date, so day differences are DST-proof (a local
/// spring-forward day is 23h and would otherwise truncate to 0 days).
DateTime _utcDateOnly(DateTime d) => DateTime.utc(d.year, d.month, d.day);

String _iso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

/// Check-in streak state: current run, all-time best, the last check-in
/// date, and the last [historyCap] check-in days (for the dots row).
class StreakState {
  final int current;
  final int best;
  final DateTime? lastCheckIn; // local calendar date, null = never
  final List<DateTime> history; // check-in days, oldest -> newest

  static const int historyCap = 30;

  const StreakState({
    this.current = 0,
    this.best = 0,
    this.lastCheckIn,
    this.history = const [],
  });

  /// Records a check-in on [day]'s local calendar date.
  ///
  /// - Same day as (or earlier than) the last check-in: no-op — repeats and
  ///   clock rollbacks can never inflate the streak.
  /// - Exactly the day after the last check-in: increments the run.
  /// - Any gap (or first ever): starts a new run at 1.
  StreakState record(DateTime day) {
    final d = _dateOnly(day);
    final last = lastCheckIn == null ? null : _dateOnly(lastCheckIn!);
    if (last != null && !last.isBefore(d)) return this;
    final gap = last == null
        ? null
        : _utcDateOnly(d).difference(_utcDateOnly(last)).inDays;
    final next = gap == 1 ? current + 1 : 1;
    // After a relapse reset lastCheckIn is cleared but history is kept, so a
    // same-day restart must not duplicate today's history entry.
    final alreadyLogged = history.isNotEmpty && history.last == d;
    final h = alreadyLogged ? history : [...history, d];
    return StreakState(
      current: next,
      best: next > best ? next : best,
      lastCheckIn: d,
      history: h.length > historyCap ? h.sublist(h.length - historyCap) : h,
    );
  }

  /// Whether [day]'s local calendar date has a recorded check-in.
  bool checkedIn(DateTime day) {
    final d = _dateOnly(day);
    return history.any((h) => h == d);
  }

  factory StreakState.fromJson(Map<String, dynamic> json) {
    final rawCurrent = json['current'];
    final rawBest = json['best'];
    DateTime? last;
    final rawLast = json['last'];
    if (rawLast is String && rawLast.isNotEmpty) {
      final parsed = DateTime.tryParse(rawLast);
      if (parsed != null) last = _dateOnly(parsed);
    }
    final rawHistory = json['history'];
    final history = rawHistory is List
        ? rawHistory
            .whereType<String>()
            .map(DateTime.tryParse)
            .whereType<DateTime>()
            .map(_dateOnly)
            .toList()
        : <DateTime>[];
    return StreakState(
      current: rawCurrent is int && rawCurrent > 0 ? rawCurrent : 0,
      best: rawBest is int && rawBest > 0 ? rawBest : 0,
      lastCheckIn: last,
      history: history.length > historyCap
          ? history.sublist(history.length - historyCap)
          : history,
    );
  }

  Map<String, dynamic> toJson() => {
        'current': current,
        'best': best,
        'last': lastCheckIn == null ? null : _iso(lastCheckIn!),
        'history': history.map(_iso).toList(),
      };
}

/// Owns the persisted [StreakState]. Check-ins are recorded by the evening
/// review, the mood check-in, a completed meditation, and the explicit
/// "Check in" tap — all same-day idempotent via [StreakState.record].
class StreakNotifier extends Notifier<StreakState> {
  static const String prefsKey = 'streak_v1';

  @override
  StreakState build() {
    final raw = ref.read(sharedPreferencesProvider).getString(prefsKey);
    if (raw == null || raw.isEmpty) return const StreakState();
    try {
      return StreakState.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return const StreakState();
    }
  }

  /// Records today's check-in (idempotent per day). [now] is a test seam;
  /// production callers omit it.
  Future<void> recordCheckIn({DateTime? now}) async {
    final next = state.record(now ?? DateTime.now());
    if (identical(next, state)) return; // same day — nothing to write
    state = next;
    await _persist();
  }

  /// A relapse restarts the current run. The best streak and the check-in
  /// history are kept — the days the user showed up are facts, and erasing
  /// them would punish (contra the FR1 shame-free design). Clearing
  /// [StreakState.lastCheckIn] lets a same-day check-in start the new run
  /// immediately: "you can always start again" applies today, not tomorrow.
  Future<void> reset() async {
    final s = state;
    if (s.current == 0 && s.lastCheckIn == null) return;
    state = StreakState(current: 0, best: s.best, history: s.history);
    await _persist();
  }

  Future<void> _persist() async {
    await ref.read(sharedPreferencesProvider).setString(
          prefsKey,
          jsonEncode(state.toJson()),
        );
  }
}
