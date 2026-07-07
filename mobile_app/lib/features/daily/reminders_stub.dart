import 'package:sobriety_copilot_mobile/features/daily/reminders.dart';

/// Web stub — no local notifications on this surface.
bool get remindersSupportedImpl => false;

Future<bool> ensureNotificationPermission() async => false;

Future<void> rescheduleReminders(ReminderSettings settings) async {}
