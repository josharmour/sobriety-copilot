import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:archive/archive_io.dart' show extractFileToDisk;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import 'package:sobriety_copilot_mobile/providers.dart';
import 'asr_types.dart';

// Re-export the shared types so importers of asr_manager.dart keep seeing
// AsrStatus / AsrInstallState / kAsrDownloadMB regardless of platform.
export 'asr_types.dart';

/// On-device speech-to-text model (sherpa-onnx streaming Zipformer, English).
///
/// Same download/extract lifecycle as the neural TTS voices. There is no
/// server-side transcription — dictation never leaves the device.
const String kAsrModelDirName = 'sherpa-onnx-streaming-zipformer-en-20M-2023-02-17';
const String kAsrArchiveUrl =
    'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'
    'sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2';

const String _completeMarker = '.complete';

/// Owns the on-disk lifecycle of the dictation model: download, extract,
/// delete. Mirrors VoiceManagerNotifier so the two stay easy to reason about.
class AsrManagerNotifier extends Notifier<AsrStatus> {
  String? _root;

  @override
  AsrStatus build() {
    unawaited(_scan());
    return AsrStatus.notInstalled;
  }

  Future<String> _rootDir() async {
    if (_root != null) return _root!;
    final dir = await getApplicationSupportDirectory();
    _root = '${dir.path}/asr_models';
    await Directory(_root!).create(recursive: true);
    return _root!;
  }

  Future<void> _scan() async {
    final root = await _rootDir();
    if (File('$root/$kAsrModelDirName/$_completeMarker').existsSync()) {
      state = AsrStatus.installed;
    }
  }

  /// Absolute model directory when installed, else null. Synchronous for the
  /// recognizer; relies on [_scan]/[download] having resolved [_root].
  String? installedDir() {
    final root = _root;
    if (root == null || !state.isInstalled) return null;
    return '$root/$kAsrModelDirName';
  }

  Future<void> download() async {
    if (state.isBusy) return;
    final root = await _rootDir();
    final archivePath = '$root/$kAsrModelDirName.tar.bz2';
    final client = ref.read(httpClientProvider);

    state = const AsrStatus(AsrInstallState.downloading);
    try {
      final request = http.Request('GET', Uri.parse(kAsrArchiveUrl));
      final response = await client.send(request);
      if (response.statusCode != 200) {
        throw HttpException('HTTP ${response.statusCode}');
      }
      final total = response.contentLength ?? kAsrDownloadMB * 1024 * 1024;
      final sink = File(archivePath).openWrite();
      var received = 0;
      var lastShown = 0.0;
      try {
        await for (final chunk in response.stream) {
          sink.add(chunk);
          received += chunk.length;
          final p = (received / total).clamp(0.0, 1.0);
          if (p - lastShown >= 0.01) {
            lastShown = p;
            state = AsrStatus(AsrInstallState.downloading, progress: p);
          }
        }
      } finally {
        await sink.close();
      }

      state = const AsrStatus(AsrInstallState.extracting);
      await Isolate.run(() => extractFileToDisk(archivePath, root));
      await File('$root/$kAsrModelDirName/$_completeMarker').create();
      state = AsrStatus.installed;
    } catch (e) {
      state = AsrStatus(AsrInstallState.error, error: e.toString());
      try {
        await Directory('$root/$kAsrModelDirName').delete(recursive: true);
      } catch (_) {}
    } finally {
      try {
        await File(archivePath).delete();
      } catch (_) {}
    }
  }

  Future<void> delete() async {
    final root = await _rootDir();
    try {
      await Directory('$root/$kAsrModelDirName').delete(recursive: true);
    } catch (_) {}
    state = AsrStatus.notInstalled;
  }
}

final asrManagerProvider =
    NotifierProvider<AsrManagerNotifier, AsrStatus>(AsrManagerNotifier.new);
