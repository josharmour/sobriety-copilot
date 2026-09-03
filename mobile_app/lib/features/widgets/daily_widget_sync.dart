import 'package:intl/intl.dart';
import '../daily/daily_readings.dart';
import '../milestones/widget_sync.dart';

/// Helper to sync today's reading to iOS and Android home-screen widgets.
class DailyWidgetSync {
  static Future<void> syncTodayReading(DailyReadingsBundle bundle) async {
    final now = DateTime.now();
    final reading = bundle.forDate(now);
    final dateIso = DateFormat('yyyy-MM-dd').format(now);

    await syncDailyReflectionWidget(
      title: reading.title,
      body: reading.body,
      source: reading.source,
      dateIso: dateIso,
    );
  }
}
