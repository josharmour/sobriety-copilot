/// HTTP client for the concept graph (`/api/graph2/*`).
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import 'concept_models.dart';

class ConceptApi {
  final String baseUrl;
  final http.Client _client;

  ConceptApi(String baseUrl, {http.Client? client})
      : baseUrl = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl,
        _client = client ?? http.Client();

  Future<Map<String, dynamic>> _get(String path, [Map<String, String>? query]) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query == null || query.isEmpty ? null : query);
    final resp = await _client.get(uri).timeout(const Duration(seconds: 40));
    final body = resp.body.isEmpty ? <String, dynamic>{} : json.decode(utf8.decode(resp.bodyBytes));
    if (resp.statusCode == 202) {
      final progress = (body as Map<String, dynamic>)['progress'] as Map<String, dynamic>? ?? const {};
      throw ConceptGraphBuilding(progress['message']?.toString() ?? 'building', (progress['pct'] as num?)?.toInt() ?? 0);
    }
    if (resp.statusCode == 404 && path == '/api/graph2/map') {
      throw const ConceptGraphUnsupported();
    }
    if (resp.statusCode != 200) {
      final detail = body is Map ? (body['detail'] ?? body['error'] ?? '') : '';
      throw Exception('HTTP ${resp.statusCode} $path $detail'.trim());
    }
    return body as Map<String, dynamic>;
  }

  Future<ConceptMap> map() async => ConceptMap.fromJson(await _get('/api/graph2/map'));

  Future<NodeDetail> node(String id, {int peers = 300}) async =>
      NodeDetail.fromJson(await _get('/api/graph2/node', {'id': id, 'peers': '$peers'}));

  Future<MeetResult> meet(String a, String b, {int offset = 0, int limit = 12}) async =>
      MeetResult.fromJson(await _get('/api/graph2/meet', {'a': a, 'b': b, 'offset': '$offset', 'limit': '$limit'}));

  Future<BookConcepts> book(String docId) async => BookConcepts.fromJson(await _get('/api/graph2/book/$docId'));

  Future<ChapterConcepts> chapter(String docId, int section) async =>
      ChapterConcepts.fromJson(await _get('/api/graph2/chapter/$docId/$section'));

  Future<ConceptSearch> search(String q) async => ConceptSearch.fromJson(await _get('/api/graph2/search', {'q': q}));
}

/// The server predates the concept graph; the caller falls back to the topic graph.
class ConceptGraphUnsupported implements Exception {
  const ConceptGraphUnsupported();
}
