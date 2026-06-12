import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:archive/archive_io.dart' show extractFileToDisk;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import 'package:sobriety_copilot_mobile/features/tts/neural_voices.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

enum VoiceInstallState { notInstalled, downloading, extracting, installed, error }

class VoiceStatus {
  final VoiceInstallState state;

  /// Download progress 0..1 (only meaningful while [VoiceInstallState.downloading]).
  final double progress;
  final String? error;

  const VoiceStatus(this.state, {this.progress = 0, this.error});

  static const notInstalled = VoiceStatus(VoiceInstallState.notInstalled);
  static const installed = VoiceStatus(VoiceInstallState.installed);

  bool get isInstalled => state == VoiceInstallState.installed;
  bool get isBusy =>
      state == VoiceInstallState.downloading ||
      state == VoiceInstallState.extracting;
}

/// Marker file written after a successful extraction so a half-extracted
/// directory never counts as installed.
const String _completeMarker = '.complete';

/// Owns the on-disk lifecycle of neural voices: download, extract, delete.
/// State maps voice id -> [VoiceStatus].
class VoiceManagerNotifier extends Notifier<Map<String, VoiceStatus>> {
  String? _voicesRoot;

  @override
  Map<String, VoiceStatus> build() {
    unawaited(_scanInstalled());
    return {
      for (final v in kNeuralVoices) v.id: VoiceStatus.notInstalled,
    };
  }

  Future<String> _root() async {
    if (_voicesRoot != null) return _voicesRoot!;
    final dir = await getApplicationSupportDirectory();
    _voicesRoot = '${dir.path}/tts_voices';
    await Directory(_voicesRoot!).create(recursive: true);
    return _voicesRoot!;
  }

  Future<void> _scanInstalled() async {
    final root = await _root();
    final next = Map<String, VoiceStatus>.from(state);
    for (final v in kNeuralVoices) {
      if (File('$root/${v.dirName}/$_completeMarker').existsSync()) {
        next[v.id] = VoiceStatus.installed;
      }
    }
    state = next;
  }

  /// Absolute model directory for an installed voice, else null.
  /// Synchronous so the TTS engine can resolve it without awaiting; relies on
  /// [_scanInstalled]/[download] having populated [_voicesRoot].
  String? installedDir(String voiceId) {
    final v = neuralVoiceById(voiceId);
    final root = _voicesRoot;
    if (v == null || root == null) return null;
    if (state[voiceId]?.isInstalled != true) return null;
    return '$root/${v.dirName}';
  }

  void _set(String id, VoiceStatus status) {
    state = {...state, id: status};
  }

  Future<void> download(NeuralVoice voice) async {
    if (state[voice.id]?.isBusy == true) return;
    final root = await _root();
    final archivePath = '$root/${voice.dirName}.tar.bz2';
    final client = ref.read(httpClientProvider);

    _set(voice.id, const VoiceStatus(VoiceInstallState.downloading));
    try {
      final request = http.Request('GET', Uri.parse(voice.archiveUrl));
      final response = await client.send(request);
      if (response.statusCode != 200) {
        throw HttpException('HTTP ${response.statusCode}');
      }
      final total = response.contentLength ?? voice.sizeMB * 1024 * 1024;
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
            _set(voice.id,
                VoiceStatus(VoiceInstallState.downloading, progress: p));
          }
        }
      } finally {
        await sink.close();
      }

      _set(voice.id, const VoiceStatus(VoiceInstallState.extracting));
      // bz2 decode of a few hundred MB is CPU-bound; keep it off the UI thread.
      await Isolate.run(() => extractFileToDisk(archivePath, root));
      await File('$root/${voice.dirName}/$_completeMarker').create();
      _set(voice.id, VoiceStatus.installed);
    } catch (e) {
      _set(voice.id,
          VoiceStatus(VoiceInstallState.error, error: e.toString()));
      try {
        await Directory('$root/${voice.dirName}').delete(recursive: true);
      } catch (_) {}
    } finally {
      try {
        await File(archivePath).delete();
      } catch (_) {}
    }
  }

  Future<void> delete(NeuralVoice voice) async {
    final root = await _root();
    try {
      await Directory('$root/${voice.dirName}').delete(recursive: true);
    } catch (_) {}
    _set(voice.id, VoiceStatus.notInstalled);
  }
}
