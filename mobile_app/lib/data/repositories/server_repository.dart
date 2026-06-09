import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:sobriety_copilot_mobile/data/models/meeting_models.dart';

/// Talks to the backend's `/api/health` endpoint and performs a lightweight
/// connectivity check. [baseUrl] is read live (no trailing slash) so a change
/// in settings takes effect immediately.
class ServerRepository {
  final http.Client client;
  final String Function() baseUrl;

  ServerRepository({required this.client, required this.baseUrl});

  /// GET /api/health -> [HealthStatus].
  ///
  /// Throws on non-2xx (surfacing the body's `{"error":...}` when present) or
  /// on network failure.
  Future<HealthStatus> health() async {
    final uri = Uri.parse('${baseUrl()}/api/health');
    final http.Response res;
    try {
      res = await client.get(uri).timeout(const Duration(seconds: 10));
    } catch (_) {
      throw Exception('Connection error. Is the server running?');
    }

    final body = res.body;
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(_errorFrom(body) ?? 'Health check failed (${res.statusCode})');
    }

    final Map<String, dynamic> json;
    try {
      json = jsonDecode(body) as Map<String, dynamic>;
    } catch (_) {
      throw Exception('Unexpected health response.');
    }
    return HealthStatus.fromJson(json);
  }

  /// True if /api/health returns 200 within a short timeout.
  Future<bool> checkConnection() async {
    try {
      final res = await client
          .get(Uri.parse('${baseUrl()}/api/health'))
          .timeout(const Duration(seconds: 5));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Extracts `{"error": "..."}` from a JSON body, if present.
  String? _errorFrom(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final err = decoded['error'];
        if (err is String && err.isNotEmpty) return err;
      }
    } catch (_) {
      // not JSON; fall through
    }
    return null;
  }
}
