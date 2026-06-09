import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:sobriety_copilot_mobile/data/models/meeting_models.dart';

/// Repository for location + meeting lookups.
///
/// - `GET /api/geocode?q=` -> [GeoResult]
/// - `GET /api/meetings?lat=&lng=&radius_mi=&max=&day=&attendance=&fellowship=`
///   -> [MeetingSearchResult]
///
/// [baseUrl] is read live (a closure) so changing it in settings takes effect
/// immediately without rebuilding this repository.
class MeetingRepository {
  final http.Client client;
  final String Function() baseUrl;

  MeetingRepository({required this.client, required this.baseUrl});

  String get _base => baseUrl().replaceAll(RegExp(r'/+$'), '');

  /// Reads an `{"error": ...}` message from a response body, or falls back to
  /// the HTTP status line.
  String _errorFor(http.Response res) {
    try {
      final decoded = json.decode(res.body);
      if (decoded is Map && decoded['error'] != null) {
        return decoded['error'].toString();
      }
    } catch (_) {
      // body wasn't JSON; fall through to status text
    }
    final reason = res.reasonPhrase;
    if (reason != null && reason.isNotEmpty) {
      return 'HTTP ${res.statusCode}: $reason';
    }
    return 'HTTP ${res.statusCode}';
  }

  /// GET /api/geocode?q=
  ///
  /// Throws on non-2xx (including 404 "no match").
  Future<GeoResult> geocode(String query) async {
    final uri = Uri.parse('$_base/api/geocode').replace(
      queryParameters: {'q': query},
    );
    final res = await client.get(uri);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(_errorFor(res));
    }
    final decoded = json.decode(res.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Unexpected geocode response.');
    }
    return GeoResult.fromJson(decoded);
  }

  /// GET /api/meetings?lat=&lng=&radius_mi=&max=&day=&attendance=&fellowship=
  ///
  /// [attendance] in {inperson, online, all}; [fellowship] in {aa, na, all}.
  Future<MeetingSearchResult> meetings({
    required double lat,
    required double lng,
    double radiusMi = 30,
    int max = 100,
    int? day,
    String? attendance,
    String? fellowship,
  }) async {
    final params = <String, String>{
      'lat': lat.toString(),
      'lng': lng.toString(),
      'radius_mi': radiusMi.toString(),
      'max': max.toString(),
    };
    if (day != null) params['day'] = day.toString();
    if (attendance != null && attendance.isNotEmpty) {
      params['attendance'] = attendance;
    }
    if (fellowship != null && fellowship.isNotEmpty) {
      params['fellowship'] = fellowship;
    }

    final uri =
        Uri.parse('$_base/api/meetings').replace(queryParameters: params);
    final res = await client.get(uri);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(_errorFor(res));
    }
    final decoded = json.decode(res.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Unexpected meetings response.');
    }
    return MeetingSearchResult.fromJson(decoded);
  }
}
