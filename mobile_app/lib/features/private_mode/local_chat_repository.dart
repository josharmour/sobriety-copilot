import 'dart:async';

import 'package:flutter_gemma/flutter_gemma.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/data/repositories/library_repository.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/crisis_interceptor.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/local_prompts.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/model_manager.dart';

/// Fully on-device chat: Gemma 4 E2B (flutter_gemma / LiteRT-LM) for
/// generation, the offline library pack's FTS5 index for retrieval. No
/// network request is made anywhere in this path.
///
/// Event contract (mirrors HttpChatRepository so ChatNotifier is unchanged):
/// SourcesEvent → TokenEvent* → DoneEvent, then the stream closes;
/// ErrorEvent terminates early. Followups/diffusion/thinking are not
/// emitted in local mode.
class LocalChatRepository implements ChatRepository {
  final LibraryRepository library;

  LocalChatRepository({required this.library});

  static const int _maxContextChunks = 4;
  static const int _maxChunkChars = 700;
  static const int _maxHistoryTurns = 4;
  static const int _maxHistoryChars = 320;

  /// The loaded native model is expensive (~seconds, GBs of RAM); keep one
  /// per process and reuse it across messages. Guarded by [_loading] so
  /// concurrent sends don't double-initialize.
  static InferenceModel? _model;
  static Future<InferenceModel>? _loading;

  static Future<InferenceModel> _ensureModel() {
    final existing = _model;
    if (existing != null) return Future.value(existing);
    return _loading ??= () async {
      try {
        // Standard model on GPU, CPU as fallback. NOTE: do NOT add an NPU
        // rung with the Tensor-G5 model build — its tf_lite_mtp_aux component
        // CHECK-aborts natively in the LiteRT runtime bundled with
        // flutter_gemma 0.13.6 (kills the whole app; not catchable here).
        // Revisit when the plugin ships litertlm-android > 0.10.0.
        final stdFile = await PrivateModelNotifier.resolveModelFile();
        if (stdFile == null) {
          throw StateError('Model file not found — download it in Settings.');
        }
        final attempts = <PreferredBackend>[
          PreferredBackend.gpu,
          PreferredBackend.cpu,
        ];
        Object? lastError;
        for (final backend in attempts) {
          try {
            await FlutterGemma.installModel(
              modelType: ModelType.gemmaIt,
              fileType: ModelFileType.litertlm,
            ).fromFile(stdFile.path).install();
            final model = await FlutterGemma.getActiveModel(
              maxTokens: 4096,
              preferredBackend: backend,
            );
            final probe = await model.createSession();
            await probe.close();
            _model = model;
            return model;
          } catch (e) {
            lastError = e;
          }
        }
        throw StateError('Could not load the on-device model: $lastError');
      } finally {
        _loading = null;
      }
    }();
  }

  /// Frees the native model (used when Private Mode is switched off or the
  /// model file is deleted).
  static Future<void> releaseModel() async {
    final m = _model;
    _model = null;
    if (m != null) {
      try {
        await m.close();
      } catch (_) {}
    }
  }

  /// FTS5 MATCH treats many characters as syntax; quote each word so raw
  /// user text can't produce a query error (library.search returns [] on
  /// exceptions, silently losing retrieval).
  static const Set<String> _stopwords = {
    'the', 'and', 'for', 'that', 'this', 'with', 'from', 'what', 'when',
    'where', 'which', 'who', 'whom', 'why', 'how', 'does', 'did', 'has',
    'have', 'had', 'was', 'were', 'are', 'you', 'your', 'not', 'but',
    'about', 'into', 'out', 'can', 'could', 'should', 'would', 'say',
    'says', 'tell', 'show', 'help', 'please',
  };

  /// Content words only, longest first, capped — big OR unions over
  /// stopwords rank poorly and have misbehaved on-device.
  List<String> _contentWords(String message) {
    final words = message
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9\s]'), ' ')
        .split(RegExp(r'\s+'))
        .where((w) => w.length > 2 && !_stopwords.contains(w))
        .toSet()
        .toList()
      ..sort((x, y) => y.length.compareTo(x.length));
    return words.take(6).toList();
  }

  String _ftsQuery(String message) {
    final words = _contentWords(message);
    if (words.isEmpty) return '';
    return words.map((w) => '"$w"').join(' OR ');
  }

  @override
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
  }) async* {
    InferenceChat? chat;
    try {
      // 1. Deterministic crisis layer — fires before and regardless of the
      //    model, mirroring the server prompt's helpline-first rule.
      final crisis = isCrisisMessage(message);

      // 2. Retrieval from the offline pack (BM25 via FTS5).
      var sources = const <Source>[];
      var context = '';
      final ftsQuery = _ftsQuery(message);
      final packInstalled = await library.isPackInstalled;
      // Retrieval diagnostics — shows in `adb logcat` as "I flutter:".
      // ignore: avoid_print
      print('[PrivateMode] packInstalled=$packInstalled '
          'ftsQuery=${ftsQuery.isEmpty ? '(empty)' : ftsQuery}');
      if (ftsQuery.isNotEmpty && packInstalled) {
        var allHits = await library.search(ftsQuery);
        // ignore: avoid_print
        print('[PrivateMode] hits=${allHits.length}'
            '${allHits.isEmpty ? '' : ' first=${allHits.first.docId}'}');
        if (allHits.isEmpty) {
          // Fallback: the combined query found nothing (or errored) —
          // probe the strongest terms one at a time and pool the results.
          final pooled = <OfflineSearchResult>[];
          final seen = <String>{};
          for (final w in _contentWords(message).take(3)) {
            final termHits = await library.search('"$w"');
            // ignore: avoid_print
            print('[PrivateMode] term "$w" hits=${termHits.length}');
            for (final h in termHits) {
              if (seen.add('${h.docId}/${h.blockId}')) pooled.add(h);
            }
            if (pooled.length >= _maxContextChunks) break;
          }
          allHits = pooled;
        }
        final hits = allHits.take(_maxContextChunks);
        final books = await library.getBooks();
        final titles = {
          for (final b in books) b.docId: b.title,
        };
        final srcs = <Source>[];
        final ctx = StringBuffer();
        var rank = 0;
        for (final h in hits) {
          final title = titles[h.docId] ?? h.docId;
          final text = h.text.length > _maxChunkChars
              ? '${h.text.substring(0, _maxChunkChars)}…'
              : h.text;
          ctx.writeln('From "$title"'
              '${h.heading.isNotEmpty ? ' — ${h.heading}' : ''}:');
          ctx.writeln(text.trim());
          ctx.writeln();
          srcs.add(Source(
            source: title,
            // Rank-derived ordering signal (BM25 has no 0..1 similarity).
            similarity: (0.9 - rank * 0.07).clamp(0.5, 1.0),
            url: '',
            excerpt: text.trim(),
            docId: h.docId,
            blockIds: [h.blockId],
          ));
          rank++;
        }
        sources = srcs;
        context = ctx.toString().trim();
      }
      yield SourcesEvent(sources);

      if (crisis) {
        yield const TokenEvent(crisisPreamble);
      }

      // 3. Prompt assembly. InferenceChat has its own history, but the
      //    repository is stateless per send, so recent turns are folded
      //    into the user message (kept tiny — small model, small budget).
      final historyBlock = StringBuffer();
      final recent = history.length > _maxHistoryTurns
          ? history.sublist(history.length - _maxHistoryTurns)
          : history;
      for (final m in recent) {
        final text = m.text.length > _maxHistoryChars
            ? '${m.text.substring(0, _maxHistoryChars)}…'
            : m.text;
        if (text.trim().isEmpty) continue;
        historyBlock.writeln(
          '${m.role == 'user' ? 'Person' : 'You'}: ${text.trim()}',
        );
      }
      // The small model mentions anything it's given — only pass the sober
      // day count when the question is actually about sobriety time.
      final wantsDayCount = RegExp(
        r'\b(day|days|sober|sobriety|clean|milestone|birthday|anniversary|how\s+long|how\s+am\s+i\s+doing)\b',
        caseSensitive: false,
      ).hasMatch(message);
      final scopedClientContext = wantsDayCount ? clientContext : null;
      final userMessage = context.isNotEmpty
          ? localUserMessage(
              context: context,
              question: message,
              clientContext: scopedClientContext,
            )
          : localNoContextMessage(
              question: message,
              clientContext: scopedClientContext,
            );
      final fullMessage = historyBlock.isEmpty
          ? userMessage
          : 'Earlier in this conversation:\n$historyBlock\n$userMessage';

      // 4. Generate.
      final model = await _ensureModel();
      chat = await model.createChat(
        temperature: 0.7,
        topK: 40,
        topP: 0.95,
        tokenBuffer: 512,
        systemInstruction: localSystemPrompt(tone),
        modelType: ModelType.gemmaIt,
        // Gemma 4 thinking mode — feeds the app's reasoning panel.
        isThinking: showThinking,
      );
      await chat.addQuery(Message.text(text: fullMessage, isUser: true));

      await for (final response in chat.generateChatResponseAsync()) {
        if (response is TextResponse) {
          if (response.token.isNotEmpty) {
            yield TokenEvent(response.token);
          }
        } else if (response is ThinkingResponse) {
          if (showThinking && response.content.isNotEmpty) {
            yield ThinkingEvent(response.content);
          }
        }
      }
      yield const DoneEvent();
    } catch (e) {
      yield ErrorEvent('On-device model error: $e');
    } finally {
      // Runs on completion AND when the consumer cancels (stop button).
      final c = chat;
      if (c != null) {
        try {
          await c.stopGeneration();
        } catch (_) {}
        try {
          await c.close();
        } catch (_) {}
      }
    }
  }

  /// Dictation is a server feature; unavailable in Private Mode.
  @override
  Future<String> transcribe({required String audio, String? format}) async =>
      '';
}
