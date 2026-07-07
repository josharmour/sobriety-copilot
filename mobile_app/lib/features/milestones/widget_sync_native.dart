import 'dart:io';

import 'package:home_widget/home_widget.dart';

/// Pushes the tracker state to the Android home-screen widget.
///
/// The widget's Kotlin side recomputes the day count at render time from
/// [dateIso] (local calendar date, `yyyy-MM-dd`), so the count stays correct
/// without any Dart background work. Desktop builds are a no-op — the
/// home_widget plugin only registers on Android/iOS.
Future<void> syncSobrietyWidget({
  String? dateIso,
  required bool discreet,
}) async {
  if (!Platform.isAndroid && !Platform.isIOS) return;
  try {
    await HomeWidget.saveWidgetData<String?>('sobriety_date', dateIso);
    await HomeWidget.saveWidgetData<bool>('sobriety_discreet', discreet);
    await HomeWidget.updateWidget(
      androidName: 'SobrietyWidgetProvider',
      iOSName: 'SobrietyWidget',
    );
  } catch (_) {
    // Widget updates are best-effort; never let them break tracker writes.
  }
}
