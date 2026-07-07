import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';

/// Abstraction over the `/api/chat` streaming endpoint.
///
/// Implementations POST the chat request and translate the Server-Sent-Events
/// response into a stream of typed [ChatEvent]s
/// ([SourcesEvent], [ThinkingEvent], [TokenEvent], [FollowupsEvent],
/// [ErrorEvent], [DoneEvent]).
abstract class ChatRepository {
  /// POSTs to `/api/chat` and yields typed events as the SSE stream arrives.
  ///
  /// [history] is the prior turns (mapped to `{role, content}` via
  /// [ChatMessage.toHistoryJson]); callers should send the last ~10.
  ///
  /// The returned stream closes when a terminal [DoneEvent] or [ErrorEvent]
  /// is emitted, or when the underlying HTTP stream ends.
  Stream<ChatEvent> sendMessage({
    required String message,
    required List<ChatMessage> history,
    List<String>? categories,
    String? tone,
    bool showThinking = false,
    String? userId,
    List<String>? images,
    String? audio,
    String? audioFormat,
    String? clientContext,
  });

  /// Voice-to-text: POSTs a base64 audio clip to `/api/transcribe` (gemma) and
  /// returns the transcription. Returns '' on failure.
  Future<String> transcribe({required String audio, String? format});
}
