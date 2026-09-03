import 'dart:io';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'package:sobriety_copilot_mobile/features/daily/reminders.dart';

/// Notification ids — stable so re-scheduling replaces rather than stacks.
const int _morningId = 1001;
const int _eveningId = 1002;

bool get remindersSupportedImpl => Platform.isAndroid || Platform.isIOS;

final FlutterLocalNotificationsPlugin _plugin =
    FlutterLocalNotificationsPlugin();

bool _initialized = false;

Future<void> _ensureInit() async {
  if (_initialized) return;
  tzdata.initializeTimeZones();
  try {
    final info = await FlutterTimezone.getLocalTimezone();
    tz.setLocalLocation(tz.getLocation(info.identifier));
  } catch (_) {
    // Fall back to the package default (UTC) — times will still fire daily.
  }
  await _plugin.initialize(
    settings: const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(
        requestAlertPermission: false,
        requestBadgePermission: false,
        requestSoundPermission: false,
      ),
    ),
  );
  _initialized = true;
}

Future<bool> ensureNotificationPermission() async {
  if (!remindersSupportedImpl) return false;
  await _ensureInit();
  if (Platform.isAndroid) {
    final android = _plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    final granted = await android?.requestNotificationsPermission();
    return granted ?? false;
  }
  final ios = _plugin.resolvePlatformSpecificImplementation<
      IOSFlutterLocalNotificationsPlugin>();
  final granted =
      await ios?.requestPermissions(alert: true, badge: false, sound: true);
  return granted ?? false;
}

/// Cancels and re-creates both daily schedules to match [settings].
/// Notification copy is deliberately discreet — nothing recovery-specific
/// shows on the lock screen.
Future<void> rescheduleReminders(ReminderSettings settings) async {
  if (!remindersSupportedImpl) return;
  await _ensureInit();
  await _plugin.cancel(id: _morningId);
  await _plugin.cancel(id: _eveningId);

  if (settings.morningEnabled) {
    await _scheduleDaily(
      id: _morningId,
      hour: settings.morningHour,
      minute: settings.morningMinute,
      title: 'Good morning',
      body: "Today's reading is ready.",
      channelId: 'daily_reading',
      channelName: 'Morning reading',
    );
  }
  if (settings.eveningEnabled) {
    await _scheduleDaily(
      id: _eveningId,
      hour: settings.eveningHour,
      minute: settings.eveningMinute,
      title: 'Time to check in',
      body: 'A few quiet minutes before bed.',
      channelId: 'nightly_review',
      channelName: 'Evening check-in',
    );
  }
}

Future<void> _scheduleDaily({
  required int id,
  required int hour,
  required int minute,
  required String title,
  required String body,
  required String channelId,
  required String channelName,
}) async {
  final now = tz.TZDateTime.now(tz.local);
  var when =
      tz.TZDateTime(tz.local, now.year, now.month, now.day, hour, minute);
  if (!when.isAfter(now)) when = when.add(const Duration(days: 1));

  await _plugin.zonedSchedule(
    id: id,
    title: title,
    body: body,
    scheduledDate: when,
    notificationDetails: NotificationDetails(
      android: AndroidNotificationDetails(
        channelId,
        channelName,
        importance: Importance.defaultImportance,
        priority: Priority.defaultPriority,
        category: AndroidNotificationCategory.reminder,
      ),
      iOS: const DarwinNotificationDetails(),
    ),
    // Inexact daily repeat — no SCHEDULE_EXACT_ALARM permission needed.
    androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
    matchDateTimeComponents: DateTimeComponents.time,
  );
}
