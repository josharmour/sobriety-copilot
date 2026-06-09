import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';

/// HTTP/SSE implementation of [ChatRepository] against POST /api/chat.
///
/// Streams a `text/event-stream` response where each event is a line of the
/// form `data: {json}\n\n`. Comment/keepalive lines (`: keepalive`) and blank
/// lines are ignored. Each decoded JSON object is mapped to a typed
/// [ChatEvent] via [ChatEvent.fromJson]. The stream completes after a
/// [DoneEvent] or [ErrorEvent] is emitted, or when the underlying byte stream
/// ends.
class HttpChatRepository implements ChatRepository {
  final http.Client client;

  /// Pulls the live base URL (no trailing slash) from AppConfig at call time,
  /// so changing it in settings takes effect immediately.
  final String Function() baseUrl;

  HttpChatRepository({required this.client, required this.baseUrl});

  static const int _maxHistory = 10;

  @override
  Stream<ChatEvent> sendMessage({
    required String message,
    required List<ChatMessage> history,
    List<String>? categories,
    String? tone,
    bool showThinking = false,
    String? userId,
  }) async* {
    final root = baseUrl().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$root/api/chat');

    // Keep only the last ~10 turns, mapped to {role, content}.
    final trimmed = history.length > _maxHistory
        ? history.sublist(history.length - _maxHistory)
        : history;
    final historyJson = trimmed.map((m) => m.toHistoryJson()).toList();

    final body = <String, dynamic>{
      'message': message,
      'history': historyJson,
      'categories': categories,
      'tone': tone,
      'show_thinking': showThinking,
      'user_id': userId,
    };

    final request = http.Request('POST', uri)
      ..headers['Content-Type'] = 'application/json'
      ..headers['Accept'] = 'text/event-stream'
      ..body = json.encode(body);

    http.StreamedResponse response;
    try {
      response = await client.send(request);
    } catch (_) {
      yield const ErrorEvent('Connection error. Is the server running?');
      return;
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final raw = await response.stream.bytesToString();
      yield ErrorEvent(_extractError(raw, response.statusCode, response.reasonPhrase));
      return;
    }

    final lines = response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter());

    try {
      await for (final line in lines) {
        final trimmedLine = line.trimRight();
        if (trimmedLine.isEmpty) continue;
        // SSE comment / keepalive lines start with ':'.
        if (trimmedLine.startsWith(':')) continue;
        if (!trimmedLine.startsWith('data:')) continue;

        final payload = trimmedLine.substring('data:'.length).trim();
        if (payload.isEmpty || payload == '[DONE]') {
          if (payload == '[DONE]') {
            yield const DoneEvent();
            return;
          }
          continue;
        }

        Map<String, dynamic> decoded;
        try {
          final obj = json.decode(payload);
          if (obj is! Map<String, dynamic>) continue;
          decoded = obj;
        } catch (_) {
          continue; // ignore malformed fragments
        }

        final event = ChatEvent.fromJson(decoded);
        if (event == null) continue;

        yield event;

        if (event is DoneEvent || event is ErrorEvent) {
          return;
        }
      }
    } catch (_) {
      yield const ErrorEvent('Connection error. Is the server running?');
    }
  }

  /// Builds a useful error message from a non-2xx response body.
  String _extractError(String raw, int status, String? reason) {
    if (raw.isNotEmpty) {
      try {
        final obj = json.decode(raw);
        if (obj is Map<String, dynamic> && obj['error'] != null) {
          return obj['error'].toString();
        }
      } catch (_) {
        // not JSON; fall through
      }
    }
    final phrase = (reason != null && reason.isNotEmpty) ? reason : 'Request failed';
    return 'Server error ($status): $phrase';
  }
}
