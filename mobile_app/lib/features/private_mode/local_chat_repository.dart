import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kDebugMode, debugPrint;

import 'package:flutter_gemma/flutter_gemma.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/data/repositories/library_repository.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/crisis_interceptor.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/embedding_manager.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/local_prompts.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/model_manager.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/vector_index.dart';

/// One retrieved block, unified across BM25 and vector search.
class _RetrievedBlock {
  final String docId;
  final String blockId;
  final String heading;
  final String text;
  final double score; // fused rank score (higher = better)
  const _RetrievedBlock(
      this.docId, this.blockId, this.heading, this.text, this.score);
}

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
    await releaseSemantic();
  }

  // ── Semantic retrieval (EmbeddingGemma + shipped vectors) ─────────────────
  static EmbeddingModel? _embedder;
  static Future<EmbeddingModel?>? _embedderLoading;
  static VectorIndex? _vectorIndex;
  static Future<VectorIndex?>? _vectorLoading;
  static bool _semanticUnavailable = false;

  /// Loads the query embedder + shipped vector index once; returns true when
  /// semantic search is usable. Absent files (embedder not downloaded, or a
  /// v1 pack without vectors) simply disable it — BM25 still runs.
  Future<bool> _ensureSemantic() async {
    if (_semanticUnavailable) return false;
    if (_embedder != null && _vectorIndex != null) return true;

    _embedderLoading ??= () async {
      try {
        final files = await EmbeddingManagerNotifier.resolveFiles();
        if (files == null) return null;
        await FlutterGemma.installEmbedder()
            .modelFromFile(files.$1)
            .tokenizerFromFile(files.$2)
            .install();
        return await FlutterGemma.getActiveEmbedder();
      } catch (e) {
        if (kDebugMode) debugPrint('[PrivateMode] embedder load failed: $e');
        return null;
      } finally {
        _embedderLoading = null;
      }
    }();
    _vectorLoading ??= () async {
      try {
        final vf = await library.vectorFiles();
        if (vf == null) return null;
        return await VectorIndex.load(
            blobPath: vf.blob, idxPath: vf.idx, metaPath: vf.meta);
      } catch (e) {
        if (kDebugMode) debugPrint('[PrivateMode] vector load failed: $e');
        return null;
      } finally {
        _vectorLoading = null;
      }
    }();

    _embedder = await _embedderLoading;
    _vectorIndex = await _vectorLoading;
    final ok = _embedder != null && _vectorIndex != null;
    if (!ok) _semanticUnavailable = true;
    return ok;
  }

  static Future<void> releaseSemantic() async {
    _semanticUnavailable = false;
    final e = _embedder;
    _embedder = null;
    _vectorIndex?.dispose();
    _vectorIndex = null;
    if (e != null) {
      try {
        await e.close();
      } catch (_) {}
    }
  }

  /// Embeds the query and returns its int8-quantized unit vector (matching
  /// the precompute in scripts/build_pack_vectors.py), or null on failure.
  Future<Int8List?> _embedQuery(String query) async {
    final embedder = _embedder;
    if (embedder == null) return null;
    try {
      final raw = await embedder.generateEmbedding(
        query,
        taskType: TaskType.retrievalQuery,
      );
      var norm = 0.0;
      for (final v in raw) {
        norm += v * v;
      }
      norm = math.sqrt(norm);
      if (norm == 0) return null;
      final q = Int8List(raw.length);
      for (var i = 0; i < raw.length; i++) {
        final s = (raw[i] / norm) * VectorIndex.scale;
        q[i] = s.round().clamp(-127, 127);
      }
      return q;
    } catch (e) {
      if (kDebugMode) debugPrint('[PrivateMode] query embed failed: $e');
      return null;
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

  /// Hybrid retrieval: BM25 (keyword) fused with EmbeddingGemma vector
  /// (semantic) via reciprocal rank fusion. Either leg alone still works —
  /// vector search is skipped when the embedder/vectors aren't installed.
  Future<List<_RetrievedBlock>> _retrieve(String message) async {
    if (!await library.isPackInstalled) return const [];

    // BM25 leg (with the single-term fallback that already ships).
    final ftsQuery = _ftsQuery(message);
    var bm25 = ftsQuery.isEmpty
        ? const <OfflineSearchResult>[]
        : await library.search(ftsQuery);
    if (bm25.isEmpty && ftsQuery.isNotEmpty) {
      final pooled = <OfflineSearchResult>[];
      final seen = <String>{};
      for (final w in _contentWords(message).take(3)) {
        for (final h in await library.search('"$w"')) {
          if (seen.add('${h.docId}/${h.blockId}')) pooled.add(h);
        }
        if (pooled.length >= 20) break;
      }
      bm25 = pooled;
    }

    // Vector leg.
    var vec = const <VectorHit>[];
    if (await _ensureSemantic()) {
      final q = await _embedQuery(message);
      if (q != null) {
        vec = await _vectorIndex!.search(q, topK: 20);
      }
    }
    if (kDebugMode) {
      debugPrint('[PrivateMode] bm25=${bm25.length} vec=${vec.length}');
    }

    // Reciprocal rank fusion (k=60). Cache block text/heading as we see it.
    const k = 60;
    final scores = <String, double>{};
    final text = <String, String>{};
    final heading = <String, String>{};
    final ids = <String, (String, String)>{};
    String key(String d, String b) => '$d/$b';

    for (var i = 0; i < bm25.length; i++) {
      final h = bm25[i];
      final kk = key(h.docId, h.blockId);
      scores[kk] = (scores[kk] ?? 0) + 1.0 / (k + i + 1);
      text[kk] = h.text;
      heading[kk] = h.heading;
      ids[kk] = (h.docId, h.blockId);
    }
    for (var i = 0; i < vec.length; i++) {
      final h = vec[i];
      final kk = key(h.docId, h.blockId);
      scores[kk] = (scores[kk] ?? 0) + 1.0 / (k + i + 1);
      ids[kk] = (h.docId, h.blockId);
    }

    final ranked = scores.keys.toList()
      ..sort((a, b) => scores[b]!.compareTo(scores[a]!));

    final out = <_RetrievedBlock>[];
    for (final kk in ranked.take(_maxContextChunks)) {
      var t = text[kk];
      var hd = heading[kk] ?? '';
      if (t == null) {
        // Vector-only hit — fetch its text from the pack.
        final (d, b) = ids[kk]!;
        final block = await library.getBlock(d, b);
        if (block == null) continue;
        t = block.text;
        hd = block.heading;
      }
      final (d, b) = ids[kk]!;
      out.add(_RetrievedBlock(d, b, hd, t, scores[kk]!));
    }
    return out;
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

      // 2. Hybrid retrieval from the offline pack (BM25 + EmbeddingGemma
      //    vectors, fused). No network anywhere in this path.
      var sources = const <Source>[];
      var context = '';
      final hits = await _retrieve(message);
      if (hits.isNotEmpty) {
        final books = await library.getBooks();
        final titles = {for (final b in books) b.docId: b.title};
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

      // 5. "Keep exploring" follow-ups — one short extra turn in the SAME
      //    chat (its context already holds the answer, so prefill is cheap).
      //    Mirrors the server's follow-up call; failure is non-fatal.
      final followups = await _generateFollowups(chat);
      if (followups.isNotEmpty) {
        yield FollowupsEvent(followups);
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

  /// Asks the finished chat for 2–3 tappable follow-up questions. Bounded,
  /// best-effort: any error or weird output returns an empty list.
  Future<List<String>> _generateFollowups(InferenceChat chat) async {
    try {
      await chat.addQuery(Message.text(
        text: 'Suggest three short follow-up questions the person might ask '
            'next, continuing this conversation. One per line. No numbering, '
            'no quotes, no other text. Each under twelve words.',
        isUser: true,
      ));
      final buf = StringBuffer();
      await for (final r in chat.generateChatResponseAsync()) {
        if (r is TextResponse) buf.write(r.token);
        if (buf.length > 500) break; // runaway guard
      }
      final lines = buf
          .toString()
          .split('\n')
          .map((l) => l.trim().replaceFirst(RegExp(r'^[-*\d.)\s]+'), ''))
          .where((l) => l.length > 8 && l.length < 90)
          .take(3)
          .toList();
      return lines;
    } catch (_) {
      return const [];
    }
  }

  /// Dictation is a server feature; unavailable in Private Mode.
  @override
  Future<String> transcribe({required String audio, String? format}) async =>
      '';
}
