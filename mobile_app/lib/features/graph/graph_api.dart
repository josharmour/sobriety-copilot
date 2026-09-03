/// HTTP client for the corpus knowledge graph endpoints.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import 'graph_models.dart';

class GraphApi {
  final String baseUrl;
  final http.Client _client;

  GraphApi(String baseUrl, {http.Client? client})
      : baseUrl = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl,
        _client = client ?? http.Client();

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl$path').replace(queryParameters: query == null || query.isEmpty ? null : query);

  Future<Map<String, dynamic>> _getJson(String path, [Map<String, String>? query]) async {
    final resp = await _client.get(_uri(path, query)).timeout(const Duration(seconds: 25));
    final body = resp.body.isEmpty ? <String, dynamic>{} : json.decode(resp.body);
    if (resp.statusCode == 202) {
      final m = body as Map<String, dynamic>;
      return Future.error(GraphBuilding(m['status']?.toString() ?? 'building', (m['progress'] as num?)?.toInt() ?? 0));
    }
    if (resp.statusCode != 200) {
      final detail = body is Map ? (body['error'] ?? body['detail'] ?? '') : '';
      throw Exception('HTTP ${resp.statusCode} $path $detail'.trim());
    }
    return body as Map<String, dynamic>;
  }

  Future<GraphMap> map() async => GraphMap.fromJson(await _getJson('/api/graph/map'));

  Future<TopicDetail> topic(String id, {int books = 14, int perBook = 3}) async =>
      TopicDetail.fromJson(await _getJson('/api/graph/topic/$id', {'books': '$books', 'per_book': '$perBook'}));

  Future<BookDetail> book(String id) async => BookDetail.fromJson(await _getJson('/api/graph/book/$id'));

  Future<PassagePage> passages(
    String topic, {
    String? book,
    int? section,
    String sort = 'score',
    int offset = 0,
    int limit = 20,
  }) async {
    final q = <String, String>{
      'topic': topic,
      'sort': sort,
      'offset': '$offset',
      'limit': '$limit',
      if (book != null) 'book': book,
      if (section != null) 'section': '$section',
    };
    return PassagePage.fromJson(await _getJson('/api/graph/passages', q));
  }

  Future<GraphSearchResult> search(String q, {int topK = 10}) async =>
      GraphSearchResult.fromJson(await _getJson('/api/graph/search', {'q': q, 'top_k': '$topK'}));

  /// [anchor] is the passage text; the server falls back to locating it by
  /// text when the block ids no longer exist in the manifest.
  Future<DocWindow> window(String docId, List<String> blockIds, {int radius = 8, String? anchor}) async =>
      DocWindow.fromJson(
        await _getJson('/api/doc/$docId/window', {
          'blocks': blockIds.join(','),
          'radius': '$radius',
          if (anchor != null && anchor.isNotEmpty) 'q': anchor.length > 400 ? anchor.substring(0, 400) : anchor,
        }),
      );

  /// Absolute URL of the server-rendered HTML reader for a passage.
  String readerUrl(String docId, List<String> blockIds) {
    final blocks = blockIds.isEmpty ? '' : '?blocks=${Uri.encodeQueryComponent(blockIds.join(','))}';
    return '$baseUrl/api/doc/$docId$blocks';
  }
}
