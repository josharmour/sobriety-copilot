import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// On-device query embedder for semantic (vector) retrieval in Private Mode.
///
/// EmbeddingGemma-300m (`.tflite`, mixed-precision) + its SentencePiece
/// tokenizer, run through flutter_gemma's embedder. Document vectors are
/// precomputed and shipped in the library pack; the device only embeds the
/// query, so this model is smaller and faster than the chat LLM.
///
/// Under the Gemma Terms of Use (not Apache) — self-hosted for ungated
/// download; the files are also honored from the external-files sideload dir.
const String kEmbedModelName = 'EmbeddingGemma';
const String kEmbedModelFile = 'embeddinggemma.tflite';
const String kEmbedTokenizerFile = 'embeddinggemma-tokenizer.model';
const int kEmbedModelBytes = 183329528; // exact, verified
const int kEmbedTokenizerBytes = 4683319; // exact, verified

// Self-hosted mirror (Gemma Terms permit redistribution; served from the
// app backend so users need no HuggingFace account).
const String kEmbedModelUrl =
    'https://sobrietycopilot.com/api/private/embedder/model';
const String kEmbedTokenizerUrl =
    'https://sobrietycopilot.com/api/private/embedder/tokenizer';

enum EmbedPhase { notInstalled, downloading, installed, error }

class EmbedState {
  final EmbedPhase phase;
  final double progress;
  final String? error;
  const EmbedState(this.phase, {this.progress = 0, this.error});
  bool get isInstalled => phase == EmbedPhase.installed;
  bool get isDownloading => phase == EmbedPhase.downloading;
}

/// Owns the embedder file lifecycle. Mirrors PrivateModelNotifier.
class EmbeddingManagerNotifier extends Notifier<EmbedState> {
  http.Client? _client;
  bool _cancel = false;

  @override
  EmbedState build() {
    if (!_supported) return const EmbedState(EmbedPhase.notInstalled);
    _probe();
    return const EmbedState(EmbedPhase.notInstalled);
  }

  bool get _supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  static Future<String> _dir() async {
    final d = await getApplicationSupportDirectory();
    return p.join(d.path, 'embedder');
  }

  /// Resolves (modelPath, tokenizerPath) if both complete files exist in the
  /// download dir or the external-files sideload dir; else null.
  static Future<(String, String)?> resolveFiles() async {
    final candidates = <String>[await _dir()];
    try {
      final ext = await getExternalStorageDirectory();
      if (ext != null) candidates.add(ext.path);
    } catch (_) {}
    for (final base in candidates) {
      final m = File(p.join(base, kEmbedModelFile));
      final t = File(p.join(base, kEmbedTokenizerFile));
      try {
        if (await m.exists() &&
            await m.length() == kEmbedModelBytes &&
            await t.exists() &&
            await t.length() == kEmbedTokenizerBytes) {
          return (m.path, t.path);
        }
      } catch (_) {}
    }
    return null;
  }

  Future<void> _probe() async {
    if (await resolveFiles() != null) {
      state = const EmbedState(EmbedPhase.installed);
    }
  }

  Future<void> refresh() => _probe();

  Future<void> download() async {
    if (state.isDownloading) return;
    if (kEmbedModelUrl.isEmpty) {
      state = const EmbedState(EmbedPhase.error,
          error: 'No download configured — sideload the model files.');
      return;
    }
    _cancel = false;
    state = const EmbedState(EmbedPhase.downloading);
    final dir = await _dir();
    await Directory(dir).create(recursive: true);
    final client = http.Client();
    _client = client;
    try {
      await _fetch(client, kEmbedTokenizerUrl,
          p.join(dir, kEmbedTokenizerFile), kEmbedTokenizerBytes, 0.0, 0.02);
      await _fetch(client, kEmbedModelUrl, p.join(dir, kEmbedModelFile),
          kEmbedModelBytes, 0.02, 1.0);
      state = const EmbedState(EmbedPhase.installed);
    } on _Cancelled {
      state = const EmbedState(EmbedPhase.notInstalled);
    } catch (e) {
      state = _cancel
          ? const EmbedState(EmbedPhase.notInstalled)
          : EmbedState(EmbedPhase.error, error: e.toString());
    } finally {
      client.close();
      _client = null;
    }
  }

  /// Streams [url] to [dest], mapping progress into [lo]..[hi] of the bar.
  Future<void> _fetch(http.Client client, String url, String dest,
      int expectBytes, double lo, double hi) async {
    final tmp = File('$dest.part');
    final res = await client.send(http.Request('GET', Uri.parse(url)));
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('HTTP ${res.statusCode}');
    }
    final total = res.contentLength ?? expectBytes;
    final sink = tmp.openWrite();
    var got = 0;
    try {
      await for (final chunk in res.stream) {
        if (_cancel) throw const _Cancelled();
        sink.add(chunk);
        got += chunk.length;
        state = EmbedState(EmbedPhase.downloading,
            progress: lo + (hi - lo) * (got / total).clamp(0.0, 1.0));
      }
    } finally {
      await sink.close();
    }
    if (await tmp.length() != expectBytes) {
      throw Exception('Incomplete download of ${p.basename(dest)}');
    }
    final f = File(dest);
    if (await f.exists()) await f.delete();
    await tmp.rename(dest);
  }

  void cancel() {
    _cancel = true;
    _client?.close();
  }

  Future<void> delete() async {
    try {
      final dir = await _dir();
      for (final name in [kEmbedModelFile, kEmbedTokenizerFile]) {
        final f = File(p.join(dir, name));
        if (await f.exists()) await f.delete();
      }
    } catch (_) {}
    state = const EmbedState(EmbedPhase.notInstalled);
  }
}

class _Cancelled implements Exception {
  const _Cancelled();
}

final embeddingManagerProvider =
    NotifierProvider<EmbeddingManagerNotifier, EmbedState>(
  EmbeddingManagerNotifier.new,
);
