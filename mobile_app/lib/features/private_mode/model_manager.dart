import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// The on-device model for Private Mode.
///
/// Gemma 4 E2B instruction-tuned, `.litertlm` (mixed 2/4/8-bit QAT).
/// Apache-2.0, ungated on the Hugging Face CDN (verified 2026-07-07), loaded
/// by flutter_gemma's LiteRT-LM engine on Android. The file is downloaded to
/// app-support storage and used in place — same pattern as the neural TTS
/// voices in features/tts/voice_manager.dart.
const String kPrivateModelName = 'Gemma 4 E2B';
const String kPrivateModelFile = 'gemma-4-E2B-it.litertlm';
const String kPrivateModelUrl =
    'https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm';
const int kPrivateModelBytes = 2588147712; // exact size, used to verify

/// Private Mode is Android-only for now: the plugin's mobile engines are
/// battle-tested there; desktop runs a JVM sidecar we haven't validated and
/// web can't hold a 2.6 GB model.
bool get privateModeSupported =>
    !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

enum PrivateModelPhase { notInstalled, downloading, installed, error }

class PrivateModelState {
  final PrivateModelPhase phase;
  final double progress; // 0..1 while downloading
  final String? error;

  const PrivateModelState(this.phase, {this.progress = 0, this.error});

  bool get isInstalled => phase == PrivateModelPhase.installed;
  bool get isDownloading => phase == PrivateModelPhase.downloading;
}

/// Owns the model file lifecycle: download with progress, verify, delete.
class PrivateModelNotifier extends Notifier<PrivateModelState> {
  http.Client? _downloadClient;
  bool _cancelRequested = false;

  @override
  PrivateModelState build() {
    if (!privateModeSupported) {
      return const PrivateModelState(PrivateModelPhase.notInstalled);
    }
    // Async existence probe; state flips to installed shortly after startup
    // if the file is already there and complete.
    _probe();
    return const PrivateModelState(PrivateModelPhase.notInstalled);
  }

  /// Download target (app-support storage).
  static Future<String> modelPath() async {
    final dir = await getApplicationSupportDirectory();
    return p.join(dir.path, 'private_model', kPrivateModelFile);
  }

  /// Finds a complete model file in either supported location: the in-app
  /// download target, or the app's external-files dir (sideload target —
  /// `adb push <file> /sdcard/Android/data/<pkg>/files/` for testing).
  static Future<File?> resolveModelFile() async {
    final candidates = <String>[await modelPath()];
    try {
      final ext = await getExternalStorageDirectory();
      if (ext != null) {
        candidates.add(p.join(ext.path, kPrivateModelFile));
      }
    } catch (_) {
      // External storage unavailable; only the download target applies.
    }
    for (final path in candidates) {
      final file = File(path);
      try {
        if (await file.exists() && await file.length() == kPrivateModelBytes) {
          return file;
        }
      } catch (_) {}
    }
    return null;
  }

  Future<void> _probe() async {
    try {
      if (await resolveModelFile() != null) {
        state = const PrivateModelState(PrivateModelPhase.installed);
      }
    } catch (_) {
      // Leave as notInstalled.
    }
  }

  /// Re-check the filesystem (e.g. after a sideload while the app was open).
  Future<void> refresh() => _probe();

  Future<void> download() async {
    if (state.isDownloading) return;
    _cancelRequested = false;
    state = const PrivateModelState(PrivateModelPhase.downloading);

    final path = await modelPath();
    final file = File(path);
    final tmp = File('$path.part');
    await tmp.parent.create(recursive: true);

    final client = http.Client();
    _downloadClient = client;
    IOSink? sink;
    try {
      final res = await client.send(http.Request('GET', Uri.parse(kPrivateModelUrl)));
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('HTTP ${res.statusCode}');
      }
      final total = res.contentLength ?? kPrivateModelBytes;
      var received = 0;
      var lastEmit = 0;
      sink = tmp.openWrite();
      await for (final chunk in res.stream) {
        if (_cancelRequested) throw const _CancelledDownload();
        sink.add(chunk);
        received += chunk.length;
        // Throttle state updates to ~every 8 MB.
        if (received - lastEmit > 8 * 1024 * 1024) {
          lastEmit = received;
          state = PrivateModelState(
            PrivateModelPhase.downloading,
            progress: received / total,
          );
        }
      }
      await sink.flush();
      await sink.close();
      sink = null;

      final size = await tmp.length();
      if (size != kPrivateModelBytes) {
        throw Exception(
          'Download incomplete ($size of $kPrivateModelBytes bytes)',
        );
      }
      if (await file.exists()) await file.delete();
      await tmp.rename(file.path);
      state = const PrivateModelState(PrivateModelPhase.installed);
    } on _CancelledDownload {
      state = const PrivateModelState(PrivateModelPhase.notInstalled);
    } catch (e) {
      // Closing the client mid-stream surfaces as a ClientException; treat
      // any failure after a cancel request as a plain cancel, not an error.
      state = _cancelRequested
          ? const PrivateModelState(PrivateModelPhase.notInstalled)
          : PrivateModelState(PrivateModelPhase.error, error: e.toString());
    } finally {
      try {
        await sink?.close();
      } catch (_) {}
      try {
        if (await tmp.exists()) await tmp.delete();
      } catch (_) {}
      client.close();
      _downloadClient = null;
    }
  }

  void cancelDownload() {
    _cancelRequested = true;
    // Closing the client aborts the in-flight response stream promptly.
    _downloadClient?.close();
  }

  Future<void> delete() async {
    try {
      final file = await resolveModelFile();
      if (file != null) await file.delete();
    } catch (_) {}
    state = const PrivateModelState(PrivateModelPhase.notInstalled);
  }
}

class _CancelledDownload implements Exception {
  const _CancelledDownload();
}

final privateModelProvider =
    NotifierProvider<PrivateModelNotifier, PrivateModelState>(
  PrivateModelNotifier.new,
);
