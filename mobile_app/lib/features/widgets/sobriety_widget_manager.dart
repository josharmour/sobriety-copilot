import 'package:shared_preferences/shared_preferences.dart';

class SobrietyWidgetManager {
  static const String _kDaysKey = 'sobriety_widget_days';
  static const String _kLabelKey = 'sobriety_widget_label';
  static const String _kQuoteKey = 'sobriety_widget_quote';

  /// Syncs sobriety milestone counter data for Home Screen Widgets.
  static Future<void> syncWidgetData({
    required SharedPreferences prefs,
    required int daysSober,
    required String milestoneLabel,
    String? quote,
  }) async {
    try {
      await prefs.setInt(_kDaysKey, daysSober);
      await prefs.setString(_kLabelKey, milestoneLabel);
      if (quote != null) {
        await prefs.setString(_kQuoteKey, quote);
      }
    } catch (_) {}
  }
}
