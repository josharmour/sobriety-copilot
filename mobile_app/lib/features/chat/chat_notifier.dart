import 'dart:async';

import 'package:flutter/foundation.dart' show debugPrint;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/features/milestones/day_count_intent.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_distiller.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/memory_snapshot.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Immutable chat screen state.
class ChatState {
  final List<ChatMessage> messages;
  final bool isSending;
  final String? error;
  final String? conversationId; // null = unsaved/new

  /// Set by [ChatNotifier.resumeThread] (FR11 Task 5). Anchors the pinned
  /// "resumed thread" note the Wave-C UI renders, and arms the one-shot
  /// `[Previously]:` synthetic history turn on the next send so server-side
  /// retrieval folds the topic in. Cleared by [ChatNotifier.startNew].
  final ThreadRef? resumedThread;

  const ChatState({
    this.messages = const [],
    this.isSending = false,
    this.error,
    this.conversationId,
    this.resumedThread,
  });

  ChatState copyWith({
    List<ChatMessage>? messages,
    bool? isSending,
    String? error,
    String? conversationId,
    ThreadRef? resumedThread,
    bool clearError = false,
    bool clearResumedThread = false,
  }) {
    return ChatState(
      messages: messages ?? this.messages,
      isSending: isSending ?? this.isSending,
      error: clearError ? null : (error ?? this.error),
      conversationId: conversationId ?? this.conversationId,
      resumedThread: clearResumedThread
          ? null
          : (resumedThread ?? this.resumedThread),
    );
  }

  bool get isEmpty => messages.isEmpty;
}

class ChatNotifier extends Notifier<ChatState> {
  StreamSubscription<ChatEvent>? _sub;

  /// One-shot flag armed by [resumeThread]: the NEXT send prepends the
  /// synthetic `[Previously]:` turn to the backend history (Task 5), then
  /// this clears — a second send never re-injects it.
  bool _resumePending = false;

  /// Conversation ids already distilled this process (FR11 Task 3): the
  /// distiller runs exactly once per finished conversation. In-memory only —
  /// dedupe is per app session, which the fact/thread dedupe also protects.
  final Set<String> _distilledFor = <String>{};

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

    // FR11 Task 5 — resumed-thread retrieval hook: the FIRST send after
    // resumeThread() prepends a synthetic user turn naming the thread, so
    // _build_retrieval_query server-side folds it into retrieval naturally.
    // One-shot: _resumePending clears here; the sent message itself stays
    // exactly what the UI passes (Wave C calls sendMessage(resumePromptFor)).
    if (_resumePending && state.resumedThread != null) {
      final t = state.resumedThread!;
      final title = t.title.trim().toLowerCase();
      final detail = t.lastDetail.trim();
      final synthetic = detail.isEmpty
          ? '[Previously]: we were working on $title'
          : '[Previously]: we were working on $title — $detail';
      history.insert(0, ChatMessage.user(synthetic));
      _resumePending = false;
    }

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
      _maybeDistill();
      if (!completer.isCompleted) completer.complete();
    }

    // Local-only tracker context: lets the assistant speak to "day 92"
    // without the server ever storing the date. Only pass it when the message
    // is genuinely about the person's own time in recovery (see
    // queryWantsDayCount) — otherwise the model recites the count every turn.
    final sobriety = ref.read(sobrietyProvider);
    final dayCountLine = (sobriety.isTracking && queryWantsDayCount(trimmed))
        ? 'They are ${sobriety.daysSober} days sober today.'
        : null;

    final parts = <String>[if (dayCountLine != null) dayCountLine];

    // FR11 Task 4 — personal-memory snapshot merge: keep the day-count line
    // when it applies AND append the on-device memory snapshot when memory
    // is enabled (Wave C: the pref gates ALL injection) and there is
    // anything to inject. The snapshot is built <= 400 chars; the server
    // clamp was widened to 600 to fit both lines.
    if (ref.read(memoryEnabledProvider)) {
      final memory = ref.read(personalMemoryProvider);
      final snapshotInput = MemorySnapshotInput(
        triggers: memory.profile.triggers,
        goal: memory.profile.goal,
        factTexts: [
          for (final f in memory.facts.reversed.take(5)) f.text,
        ],
        threads: [
          for (final t in memory.threads)
            if (!t.resolved)
              ThreadRef(
                title: t.title,
                lastDetail: t.lastDetail,
                updatedAt: t.updatedAt,
                resolved: t.resolved,
              ),
        ],
      );
      final snapshot = hasAnythingToInject(snapshotInput)
          ? buildClientContextSnapshot(snapshotInput)
          : '';
      if (snapshot.isNotEmpty) parts.add(snapshot);
    }
    final clientContext = parts.isEmpty ? null : parts.join('\n');

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
                ? "Couldn't reach Sobriety Copilot. Check your connection "
                    'and try again.'
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
    // Distill once a finished conversation qualifies (guards inside
    // _maybeDistill: >= 4 messages, an assistant reply, a conversation id,
    // and not already distilled this session).
    _maybeDistill();
  }

  /// Resets to an empty new conversation (does not delete the saved one).
  void startNew() {
    _sub?.cancel();
    _sub = null;
    _resumePending = false;
    state = const ChatState();
  }

  /// Loads a saved conversation into the live state.
  void loadConversation(Conversation conversation) {
    _sub?.cancel();
    _sub = null;
    _resumePending = false;
    state = ChatState(
      messages: List<ChatMessage>.from(conversation.messages),
      isSending: false,
      conversationId: conversation.id,
    );
  }

  /// FR11 Task 5 — marks the conversation as a resumed thread (Wave-C UI
  /// calls this from the "Continue where we left off" chip, then sends
  /// `resumePromptFor(threadRef)` as the first message). Pins [ThreadRef] in
  /// state (the pinned-note anchor) and arms the one-shot `[Previously]:`
  /// synthetic turn that folds the topic into server-side retrieval on the
  /// NEXT send only.
  void resumeThread(MemoryThread t) {
    _resumePending = true;
    state = state.copyWith(
      resumedThread: ThreadRef(
        title: t.title,
        lastDetail: t.lastDetail,
        updatedAt: t.updatedAt,
        resolved: t.resolved,
      ),
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

  // --- FR11 Task 3: conversation-end distillation ---

  /// Fire-and-forget distillation hook, run exactly once per finished
  /// conversation id. Failure-safe by contract: any error is debugPrint-only
  /// and NEVER surfaces in chat state or blocks isSending=false.
  void _maybeDistill() {
    // Wave C gate: the not-yet-distilled conversation is discarded instead of
    // queued when memory is disabled — after re-enabling, fresh sends distill
    // their own conversation (the per-session dedupe has not marked it).
    if (!ref.read(memoryEnabledProvider)) return;
    final convId = state.conversationId;
    if (convId == null) return;
    final messages = state.messages;
    // Skip short chats (under 4 messages) and chats with no assistant reply.
    if (messages.length < 4) return;
    if (!messages.any((m) => m.isAssistant && !m.isError)) return;
    // Dedupe: distill once per conversation id (in-memory; the fact/thread
    // dedupe also protects against re-adding).
    if (!_distilledFor.add(convId)) return;

    final turns = <ChatMessage>[
      for (final m in messages)
        if ((m.isUser || m.isAssistant) && !m.isError && m.text.trim().isNotEmpty)
          m,
    ];
    final transcript = turns.length <= kDistillWindowTurns
        ? turns
        : turns.sublist(turns.length - kDistillWindowTurns);
    unawaited(_runDistill(convId, transcript));
  }

  Future<void> _runDistill(String convId, List<ChatMessage> transcript) async {
    try {
      final memory = ref.read(personalMemoryProvider);
      // Known-memory digest for dedupe: most-recent 20 fact texts (the full
      // cap-100 list would bloat the prompt) + unresolved thread titles.
      final digest = <String, dynamic>{
        'facts': [for (final f in memory.facts.reversed.take(20)) f.text],
        'threads': [
          for (final t in memory.threads)
            if (!t.resolved) t.title,
        ],
      };
      final distiller = ref.read(distillerProvider);
      final result = await distiller.distill(
        transcript,
        existingMemoryDigest: digest,
      );
      if (result.isEmpty) return;

      final mem = ref.read(personalMemoryProvider.notifier);
      for (final fact in result.newFacts) {
        await mem.addFact(fact, convId);
      }
      for (final thread in result.threads) {
        // Memory ledger: a model-marked resolved=true thread resolves the
        // matching existing thread (fuzzy title match >= 0.85) instead of
        // being re-opened; without a match it is dropped.
        final match = _existingThreadMatch(
          ref.read(personalMemoryProvider),
          thread.title,
        );
        if (thread.resolved) {
          if (match != null) await mem.resolveThread(match.id);
        } else {
          await mem.upsertThread(thread.id, thread.title, thread.detail);
        }
      }
    } catch (e) {
      // Failure-safe: never surface distillation errors in the chat UX.
      debugPrint('[PersonalMemory] distillation skipped (silent): $e');
    }
  }

  /// Case-insensitive fuzzy title match (normalized token Jaccard >= 0.85)
  /// against UNRESOLVED threads — the FR11 memory ledger for resolved=true.
  MemoryThread? _existingThreadMatch(PersonalMemory memory, String title) {
    final norm = _normalizeForMatch(title);
    if (norm.isEmpty) return null;
    MemoryThread? best;
    var bestSim = 0.0;
    for (final t in memory.threads) {
      if (t.resolved) continue;
      final sim = _tokenJaccard(norm, _normalizeForMatch(t.title));
      if (sim > bestSim) {
        bestSim = sim;
        best = t;
      }
    }
    return bestSim >= 0.85 ? best : null;
  }

  static Set<String> _normalizeForMatch(String text) {
    final t = text
        .toLowerCase()
        .replaceAll(RegExp(r'[^\p{L}\p{N}\s]', unicode: true), ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    if (t.isEmpty) return const {};
    return t.split(' ').toSet();
  }

  static double _tokenJaccard(Set<String> a, Set<String> b) {
    if (a.isEmpty && b.isEmpty) return 1;
    if (a.isEmpty || b.isEmpty) return 0;
    final union = a.union(b).length;
    if (union == 0) return 1;
    return a.intersection(b).length / union;
  }
}
