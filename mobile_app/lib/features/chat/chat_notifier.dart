import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/features/milestones/day_count_intent.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Immutable chat screen state.
class ChatState {
  final List<ChatMessage> messages;
  final bool isSending;
  final String? error;
  final String? conversationId; // null = unsaved/new

  const ChatState({
    this.messages = const [],
    this.isSending = false,
    this.error,
    this.conversationId,
  });

  ChatState copyWith({
    List<ChatMessage>? messages,
    bool? isSending,
    String? error,
    String? conversationId,
    bool clearError = false,
  }) {
    return ChatState(
      messages: messages ?? this.messages,
      isSending: isSending ?? this.isSending,
      error: clearError ? null : (error ?? this.error),
      conversationId: conversationId ?? this.conversationId,
    );
  }

  bool get isEmpty => messages.isEmpty;
}

class ChatNotifier extends Notifier<ChatState> {
  StreamSubscription<ChatEvent>? _sub;

  @override
  ChatState build() {
    ref.onDispose(() {
      _sub?.cancel();
      _sub = null;
    });
    return const ChatState();
  }

  /// Sends [text]: appends a user message + streaming assistant placeholder,
  /// consumes chatRepository.sendMessage(), folds Sources/Thinking/Token/
  /// Followups/Error/Done into the last assistant message, then persists the
  /// conversation via conversationsProvider. No-op if text is blank or sending.
  Future<void> sendMessage(
    String text, {
    List<String> images = const [],
    String? audio,
    String? audioFormat,
  }) async {
    final trimmed = text.trim();
    final hasMedia = images.isNotEmpty || (audio != null && audio.isNotEmpty);
    if ((trimmed.isEmpty && !hasMedia) || state.isSending) return;

    final AppConfig config = ref.read(appConfigProvider);

    // Prior turns become the history sent to the backend (last ~10).
    final history = List<ChatMessage>.from(state.messages);

    final userMsg = ChatMessage.user(trimmed, images: images);
    final placeholder = ChatMessage.assistantPlaceholder(query: trimmed);

    state = state.copyWith(
      messages: [...state.messages, userMsg, placeholder],
      isSending: true,
      clearError: true,
    );

    final assistantId = placeholder.id;
    final trimmedHistory =
        history.length > 10 ? history.sublist(history.length - 10) : history;

    final completer = Completer<void>();

    void finish() {
      _sub = null;
      _updateById(assistantId, (m) => m.copyWith(isStreaming: false, isDenoising: false));
      state = state.copyWith(isSending: false);
      _persist();
      if (!completer.isCompleted) completer.complete();
    }

    // Local-only tracker context: lets the assistant speak to "day 92"
    // without the server ever storing the date. Only pass it when the message
    // is genuinely about the person's own time in recovery (see
    // queryWantsDayCount) — otherwise the model recites the count every turn.
    final sobriety = ref.read(sobrietyProvider);
    final clientContext = (sobriety.isTracking && queryWantsDayCount(trimmed))
        ? 'They are ${sobriety.daysSober} days sober today.'
        : null;

    final stream = ref.read(chatRepositoryProvider).sendMessage(
          message: trimmed,
          history: trimmedHistory,
          categories: config.categoriesForRequest,
          tone: config.tone,
          showThinking: config.showThinking,
          userId: config.userId,
          images: images.isNotEmpty ? images : null,
          audio: audio,
          audioFormat: audioFormat,
          clientContext: clientContext,
        );

    _sub = stream.listen(
      (event) {
        switch (event) {
          case SourcesEvent(:final sources, :final expandedQuery):
            _updateById(
              assistantId,
              (m) => m.copyWith(
                sources: sources,
                highlightSeed:
                    (expandedQuery != null && expandedQuery.trim().isNotEmpty)
                        ? expandedQuery
                        : m.query,
              ),
            );
          case ThinkingEvent(:final text):
            _updateById(
              assistantId,
              (m) => m.copyWith(thinking: m.thinking + text),
            );
          case TokenEvent(:final text):
            _updateById(
              assistantId,
              (m) => m.copyWith(
                isDenoising: false,
                text: m.text + text,
              ),
            );
          case FollowupsEvent(:final items):
            _updateById(
              assistantId,
              (m) => m.copyWith(followups: items),
            );
          case DiffusionEvent(:final block, :final step, :final total, :final content):
            _updateById(
              assistantId,
              (m) => m.copyWith(
                isDenoising: true,
                diffusionStep: step,
                diffusionTotal: total,
                diffusionContent: content,
              ),
            );
          case ErrorEvent(:final message):
            _updateById(
              assistantId,
              (m) => m.copyWith(
                text: m.text.isEmpty ? message : m.text,
                isError: true,
                isStreaming: false,
                isDenoising: false,
              ),
            );
            state = state.copyWith(error: message);
          case DoneEvent():
            // Terminal; finalization handled in onDone.
            break;
        }
      },
      onError: (Object e) {
        _updateById(
          assistantId,
          (m) => m.copyWith(
            text: m.text.isEmpty
                ? 'Connection error. Is the server running?'
                : m.text,
            isError: true,
            isStreaming: false,
            isDenoising: false,
          ),
        );
        state = state.copyWith(error: e.toString());
        finish();
      },
      onDone: finish,
      cancelOnError: true,
    );

    return completer.future;
  }

  /// Cancels the in-flight stream (if any) and clears isSending.
  void stop() {
    _sub?.cancel();
    _sub = null;
    if (state.messages.isNotEmpty) {
      final last = state.messages.last;
      if (last.isAssistant && last.isStreaming) {
        _updateById(last.id, (m) => m.copyWith(isStreaming: false));
      }
    }
    state = state.copyWith(isSending: false);
    _persist();
  }

  /// Resets to an empty new conversation (does not delete the saved one).
  void startNew() {
    _sub?.cancel();
    _sub = null;
    state = const ChatState();
  }

  /// Loads a saved conversation into the live state.
  void loadConversation(Conversation conversation) {
    _sub?.cancel();
    _sub = null;
    state = ChatState(
      messages: List<ChatMessage>.from(conversation.messages),
      isSending: false,
      conversationId: conversation.id,
    );
  }

  /// Re-sends the last user message (used after an error).
  Future<void> retryLast() async {
    if (state.isSending) return;
    // Find the last user message.
    int lastUserIndex = -1;
    for (var i = state.messages.length - 1; i >= 0; i--) {
      if (state.messages[i].isUser) {
        lastUserIndex = i;
        break;
      }
    }
    if (lastUserIndex < 0) return;
    final text = state.messages[lastUserIndex].text;
    // Drop the failed user turn + everything after it, then resend cleanly.
    final kept = state.messages.sublist(0, lastUserIndex);
    state = state.copyWith(messages: kept, clearError: true);
    await sendMessage(text);
  }

  // --- internals ---

  void _updateById(String id, ChatMessage Function(ChatMessage) update) {
    final idx = state.messages.indexWhere((m) => m.id == id);
    if (idx < 0) return;
    final updated = List<ChatMessage>.from(state.messages);
    updated[idx] = update(updated[idx]);
    state = state.copyWith(messages: updated);
  }

  void _persist() {
    if (state.messages.isEmpty) return;
    // Only persist once there is at least one assistant answer.
    final hasAssistant = state.messages.any((m) => m.isAssistant);
    if (!hasAssistant) return;

    final convs = ref.read(conversationsProvider.notifier);
    final now = DateTime.now();
    Conversation conv;
    final existingId = state.conversationId;
    if (existingId != null) {
      final existing = convs.byId(existingId);
      final base = existing ?? Conversation.create();
      conv = base.copyWith(
        title: Conversation.deriveTitle(state.messages),
        messages: List<ChatMessage>.from(state.messages),
        updatedAt: now,
      );
      // If the existing was null (deleted), keep its id by using base's id.
      if (existing == null && base.id != existingId) {
        state = state.copyWith(conversationId: base.id);
      }
    } else {
      final created = Conversation.create();
      conv = created.copyWith(
        title: Conversation.deriveTitle(state.messages),
        messages: List<ChatMessage>.from(state.messages),
        updatedAt: now,
      );
      state = state.copyWith(conversationId: conv.id);
    }
    convs.upsert(conv);
  }
}
