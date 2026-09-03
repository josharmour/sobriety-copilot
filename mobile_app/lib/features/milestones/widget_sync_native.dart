import 'dart:io';

import 'package:home_widget/home_widget.dart';

const String kAppGroupId = 'group.com.sobrietycopilot.app';

/// Pushes the tracker state to the Android/iOS home-screen widget.
///
/// The widget recomputes the day count at render time from [dateIso]
/// (local calendar date, `yyyy-MM-dd`), so the count stays correct
/// without any Dart background work.
Future<void> syncSobrietyWidget({
  String? dateIso,
  required bool discreet,
  int? streakCount,
}) async {
  if (!Platform.isAndroid && !Platform.isIOS) return;
  try {
    if (Platform.isIOS) {
      await HomeWidget.setAppGroupId(kAppGroupId);
    }
    await HomeWidget.saveWidgetData<String?>('sobriety_date', dateIso);
    await HomeWidget.saveWidgetData<bool>('sobriety_discreet', discreet);
    if (streakCount != null) {
      await HomeWidget.saveWidgetData<int>('sobriety_streak', streakCount);
    }
    await HomeWidget.updateWidget(
      androidName: 'SobrietyWidgetProvider',
      iOSName: 'SobrietyCounterWidget',
    );
  } catch (_) {
    // Widget updates are best-effort; never let them break tracker writes.
  }
}

/// Pushes the daily reflection passage to home-screen widgets.
Future<void> syncDailyReflectionWidget({
  required String title,
  required String body,
  required String source,
  required String dateIso,
}) async {
  if (!Platform.isAndroid && !Platform.isIOS) return;
  try {
    if (Platform.isIOS) {
      await HomeWidget.setAppGroupId(kAppGroupId);
    }
    await HomeWidget.saveWidgetData<String>('daily_title', title);
    await HomeWidget.saveWidgetData<String>('daily_body', body);
    await HomeWidget.saveWidgetData<String>('daily_source', source);
    await HomeWidget.saveWidgetData<String>('daily_date', dateIso);
    await HomeWidget.updateWidget(
      androidName: 'DailyReflectionWidgetProvider',
      iOSName: 'DailyReflectionWidget',
    );
  } catch (_) {
    // Best-effort.
  }
}
