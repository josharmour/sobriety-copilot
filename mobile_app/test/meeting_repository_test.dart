import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sobriety_copilot_mobile/data/repositories/meeting_repository.dart';

void main() {
  late Uri captured;
  MeetingRepository repo() => MeetingRepository(
        client: MockClient((req) async {
          captured = req.url;
          return http.Response(
              '{"meetings": [], "total_in_radius": 0, "feeds_total": 1, '
              '"feeds_with_data": 1}',
              200);
        }),
        baseUrl: () => 'https://example.org/',
      );

  test('sends Day/Time filters with the local clock (Sun=0)', () async {
    // 2026-09-22 is a Tuesday.
    await repo().meetings(
      lat: 40.7,
      lng: -74.0,
      range: 'tonight',
      timeOfDay: 'evening',
      now: DateTime(2026, 9, 22, 18, 5),
    );
    expect(captured.path, '/api/meetings');
    expect(captured.queryParameters['range'], 'tonight');
    expect(captured.queryParameters['tod'], 'evening');
    expect(captured.queryParameters['now_day'], '2');
    expect(captured.queryParameters['now_min'], '${18 * 60 + 5}');
  });

  test('Sunday maps to 0', () async {
    await repo().meetings(
        lat: 1, lng: 1, range: 'upcoming', now: DateTime(2026, 9, 20, 0, 0));
    expect(captured.queryParameters['now_day'], '0');
    expect(captured.queryParameters['now_min'], '0');
  });

  test('omits clock when no Day/Time filter is given (legacy query)',
      () async {
    await repo().meetings(lat: 1, lng: 1);
    expect(captured.queryParameters.containsKey('now_day'), isFalse);
    expect(captured.queryParameters.containsKey('range'), isFalse);
  });
}
