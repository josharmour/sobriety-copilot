import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';

/// Autocomplete client for the `GET /api/suggest` endpoint.
///
/// The server returns `[]` when the trimmed query is shorter than 2 chars, and
/// otherwise a list of `{"text": str, "source": str}` objects (it may also
/// emit bare strings, which [Suggestion.fromJson] tolerates).
///
/// All failures (network, non-2xx, decode) are swallowed and surfaced as an
/// empty list, since suggestions are a best-effort, non-critical UX affordance.
class SuggestRepository {
  final http.Client client;

  /// Pulls the live baseUrl from AppConfig (no trailing slash).
  final String Function() baseUrl;

  SuggestRepository({required this.client, required this.baseUrl});

  /// GET `/api/suggest?q=&categories=csv` -> `List<Suggestion>`.
  ///
  /// Returns `[]` for short queries (`< 2` chars after trim) or on any error.
  Future<List<Suggestion>> suggest(String q, {List<String>? categories}) async {
    final query = q.trim();
    if (query.length < 2) return const [];

    final params = <String, String>{'q': query};
    if (categories != null && categories.isNotEmpty) {
      params['categories'] = categories.join(',');
    }

    final uri = Uri.parse(
      '${baseUrl()}/api/suggest',
    ).replace(queryParameters: params);

    try {
      final resp = await client
          .get(uri, headers: const {'Accept': 'application/json'})
          .timeout(const Duration(seconds: 8));

      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        return const [];
      }

      final body = resp.body.trim();
      if (body.isEmpty) return const [];

      final decoded = json.decode(body);
      if (decoded is! List) return const [];

      final out = <Suggestion>[];
      for (final item in decoded) {
        try {
          out.add(Suggestion.fromJson(item));
        } catch (_) {
          // Skip malformed entries; keep the rest.
        }
      }
      return out;
    } catch (_) {
      return const [];
    }
  }
}
