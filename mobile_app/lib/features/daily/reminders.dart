/// Daily-practice reminder scheduling.
///
/// Native (Android/iOS) uses flutter_local_notifications with two channels
/// (morning reading, evening check-in); web and unsupported desktops are
/// no-ops so shared code can call unconditionally.
library;

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/daily/reminders_impl.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// User-configured reminder times, persisted locally.
class ReminderSettings {
  final bool morningEnabled;
  final int morningHour;
  final int morningMinute;
  final bool eveningEnabled;
  final int eveningHour;
  final int eveningMinute;

  const ReminderSettings({
    this.morningEnabled = false,
    this.morningHour = 8,
    this.morningMinute = 0,
    this.eveningEnabled = false,
    this.eveningHour = 21,
    this.eveningMinute = 0,
  });

  ReminderSettings copyWith({
    bool? morningEnabled,
    int? morningHour,
    int? morningMinute,
    bool? eveningEnabled,
    int? eveningHour,
    int? eveningMinute,
  }) {
    return ReminderSettings(
      morningEnabled: morningEnabled ?? this.morningEnabled,
      morningHour: morningHour ?? this.morningHour,
      morningMinute: morningMinute ?? this.morningMinute,
      eveningEnabled: eveningEnabled ?? this.eveningEnabled,
      eveningHour: eveningHour ?? this.eveningHour,
      eveningMinute: eveningMinute ?? this.eveningMinute,
    );
  }

  factory ReminderSettings.fromJson(Map<String, dynamic> json) =>
      ReminderSettings(
        morningEnabled: json['morningEnabled'] as bool? ?? false,
        morningHour: json['morningHour'] as int? ?? 8,
        morningMinute: json['morningMinute'] as int? ?? 0,
        eveningEnabled: json['eveningEnabled'] as bool? ?? false,
        eveningHour: json['eveningHour'] as int? ?? 21,
        eveningMinute: json['eveningMinute'] as int? ?? 0,
      );

  Map<String, dynamic> toJson() => {
        'morningEnabled': morningEnabled,
        'morningHour': morningHour,
        'morningMinute': morningMinute,
        'eveningEnabled': eveningEnabled,
        'eveningHour': eveningHour,
        'eveningMinute': eveningMinute,
      };

  static const String prefsKey = 'daily_reminders_v1';
}

/// Whether this surface can schedule reminders at all (Android/iOS).
bool get remindersSupported => remindersSupportedImpl;

class ReminderNotifier extends Notifier<ReminderSettings> {
  @override
  ReminderSettings build() {
    final raw =
        ref.read(sharedPreferencesProvider).getString(ReminderSettings.prefsKey);
    if (raw == null || raw.isEmpty) return const ReminderSettings();
    try {
      return ReminderSettings.fromJson(
        jsonDecode(raw) as Map<String, dynamic>,
      );
    } catch (_) {
      return const ReminderSettings();
    }
  }

  /// Applies [next]: persists, then (re)schedules or cancels notifications.
  /// Returns false when the user denied the notification permission.
  Future<bool> apply(ReminderSettings next) async {
    if ((next.morningEnabled || next.eveningEnabled) && remindersSupported) {
      final granted = await ensureNotificationPermission();
      if (!granted) return false;
    }
    state = next;
    await ref.read(sharedPreferencesProvider).setString(
          ReminderSettings.prefsKey,
          jsonEncode(next.toJson()),
        );
    await rescheduleReminders(next);
    return true;
  }
}

final reminderProvider =
    NotifierProvider<ReminderNotifier, ReminderSettings>(ReminderNotifier.new);
