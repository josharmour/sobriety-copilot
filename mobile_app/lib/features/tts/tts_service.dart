import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/features/tts/neural_voices.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

// ── Worker isolate ───────────────────────────────────────────────────────────
// The sherpa-onnx FFI calls are synchronous and can take seconds per sentence
// (Kokoro on CPU), so a long-lived isolate owns the model and the main isolate
// sends it {load|gen|dispose} commands.

void _ttsWorker(SendPort mainPort) {
  final commands = ReceivePort();
  mainPort.send(commands.sendPort);
  sherpa.initBindings();

  sherpa.OfflineTts? tts;
  String? loadedDir;

  sherpa.OfflineTtsConfig configFor(String dir) {
    final entries = Directory(dir).listSync();
    final onnxPath = entries
        .firstWhere((e) => e.path.endsWith('.onnx'))
        .path;
    final dataDir =
        Directory('$dir/espeak-ng-data').existsSync() ? '$dir/espeak-ng-data' : '';
    final isKokoro = File('$dir/voices.bin').existsSync();
    final model = isKokoro
        ? sherpa.OfflineTtsModelConfig(
            kokoro: sherpa.OfflineTtsKokoroModelConfig(
              model: onnxPath,
              voices: '$dir/voices.bin',
              tokens: '$dir/tokens.txt',
              dataDir: dataDir,
            ),
            numThreads: 2,
            debug: false,
          )
        : sherpa.OfflineTtsModelConfig(
            vits: sherpa.OfflineTtsVitsModelConfig(
              model: onnxPath,
              tokens: '$dir/tokens.txt',
              dataDir: dataDir,
            ),
            numThreads: 2,
            debug: false,
          );
    return sherpa.OfflineTtsConfig(model: model);
  }

  commands.listen((message) {
    final msg = message as Map;
    final reply = msg['reply'] as SendPort;
    try {
      switch (msg['cmd'] as String) {
        case 'load':
          final dir = msg['dir'] as String;
          if (loadedDir != dir) {
            tts?.free();
            tts = sherpa.OfflineTts(configFor(dir));
            loadedDir = dir;
          }
          reply.send(null);
        case 'gen':
          final audio = tts!.generate(
            text: msg['text'] as String,
            sid: msg['sid'] as int,
            speed: 1.0,
          );
          if (audio.samples.isEmpty) {
            reply.send(null);
          } else {
            final outPath = msg['out'] as String;
            sherpa.writeWave(
              filename: outPath,
              samples: audio.samples,
              sampleRate: audio.sampleRate,
            );
            reply.send(outPath);
          }
        case 'dispose':
          tts?.free();
          reply.send(null);
          commands.close();
      }
    } catch (e) {
      reply.send({'error': e.toString()});
    }
  });
}

/// Main-isolate handle to the worker. Spawned lazily on first neural speak.
class _NeuralEngine {
  SendPort? _commands;
  Future<void>? _starting;

  Future<void> _ensureStarted() {
    return _starting ??= () async {
      final fromWorker = ReceivePort();
      await Isolate.spawn(_ttsWorker, fromWorker.sendPort);
      _commands = await fromWorker.first as SendPort;
    }();
  }

  Future<dynamic> _send(Map<String, dynamic> msg) async {
    await _ensureStarted();
    final reply = ReceivePort();
    _commands!.send({...msg, 'reply': reply.sendPort});
    final result = await reply.first;
    reply.close();
    if (result is Map && result['error'] != null) {
      throw StateError('TTS engine: ${result['error']}');
    }
    return result;
  }

  Future<void> load(String modelDir) => _send({'cmd': 'load', 'dir': modelDir});

  /// Synthesizes [text] to a wav at [outPath]; returns the path, or null if
  /// the model produced no audio.
  Future<String?> synthesize(String text, int sid, String outPath) async {
    return await _send({'cmd': 'gen', 'text': text, 'sid': sid, 'out': outPath})
        as String?;
  }

  void dispose() {
    final commands = _commands;
    if (commands != null) {
      final reply = ReceivePort();
      commands.send({'cmd': 'dispose', 'reply': reply.sendPort});
      reply.first.whenComplete(reply.close);
    }
  }
}

// ── Facade ───────────────────────────────────────────────────────────────────

/// Single entry point for read-aloud: routes to the platform TTS engine or a
/// downloaded sherpa-onnx voice based on [AppConfig.voiceId]. [onDone] fires
/// when playback finishes or errors (not when interrupted via [stop]).
class AppTts {
  AppTts(this._ref) {
    _system.setCompletionHandler(() => onDone?.call());
    _system.setCancelHandler(() {});
    _system.setErrorHandler((_) => onDone?.call());
  }

  final Ref _ref;
  final FlutterTts _system = FlutterTts();
  final AudioPlayer _player = AudioPlayer();
  final _NeuralEngine _engine = _NeuralEngine();

  void Function()? onDone;

  /// Incremented on every speak/stop; in-flight neural loops check it and
  /// bail when it changes.
  int _generation = 0;
  bool _usingSystem = false;

  Future<void> speak(String text) async {
    await stop();
    final config = _ref.read(appConfigProvider);
    final voice = neuralVoiceById(config.voiceId);
    final modelDir = voice == null
        ? null
        : _ref.read(voiceManagerProvider.notifier).installedDir(voice.id);

    if (voice == null || modelDir == null) {
      _usingSystem = true;
      await _system.setSpeechRate(0.5);
      await _system.speak(text);
      return;
    }
    _usingSystem = false;
    unawaited(_speakNeural(text, voice, modelDir, ++_generation));
  }

  Future<void> stop() async {
    _generation++;
    if (_usingSystem) {
      await _system.stop();
    } else {
      await _player.stop();
    }
  }

  Future<void> _speakNeural(
    String text,
    NeuralVoice voice,
    String modelDir,
    int generation,
  ) async {
    try {
      await _engine.load(modelDir);
      if (generation != _generation) return;

      final sentences = _splitSentences(text);
      final tmp = Directory.systemTemp.path;

      // Pipeline: synthesize sentence i+1 while sentence i plays.
      Future<String?> pending =
          _engine.synthesize(sentences.first, voice.sid, '$tmp/tts_0.wav');
      for (var i = 0; i < sentences.length; i++) {
        final path = await pending;
        if (generation != _generation) return;
        if (i + 1 < sentences.length) {
          pending = _engine.synthesize(
              sentences[i + 1], voice.sid, '$tmp/tts_${(i + 1) % 2}.wav');
        }
        if (path != null) {
          await _playToEnd(path, generation);
          if (generation != _generation) return;
        }
      }
      onDone?.call();
    } catch (_) {
      if (generation == _generation) onDone?.call();
    }
  }

  Future<void> _playToEnd(String path, int generation) async {
    final done = _player.onPlayerComplete.first;
    await _player.play(DeviceFileSource(path));
    // stop() interrupts playback; poll the generation so we don't hang on a
    // completion event that will never come.
    await Future.any([
      done,
      () async {
        while (generation == _generation) {
          await Future<void>.delayed(const Duration(milliseconds: 100));
        }
      }(),
    ]);
  }

  /// Splits into speakable chunks at sentence boundaries, merging fragments
  /// so very short sentences don't produce choppy audio.
  List<String> _splitSentences(String text) {
    final parts = text.split(RegExp(r'(?<=[.!?:;])\s+'));
    final chunks = <String>[];
    var current = '';
    for (final part in parts) {
      final p = part.trim();
      if (p.isEmpty) continue;
      current = current.isEmpty ? p : '$current $p';
      if (current.length >= 60) {
        chunks.add(current);
        current = '';
      }
    }
    if (current.isNotEmpty) chunks.add(current);
    return chunks.isEmpty ? [text] : chunks;
  }

  void dispose() {
    _generation++;
    _system.stop();
    _player.dispose();
    _engine.dispose();
  }
}
