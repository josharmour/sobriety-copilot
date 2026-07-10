import 'dart:isolate';
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

/// On-device transcription of a recorded WAV clip (16 kHz mono — what the
/// chat mic records) using the installed streaming Zipformer model.
///
/// Runs in a short-lived isolate: recognizer construction plus decoding a
/// clip is CPU-bound (~1–3 s for a typical voice note) and must not jank the
/// UI. sherpa bindings are initialized inside the isolate (per-isolate FFI).
Future<String> transcribeWavFile({
  required String wavPath,
  required String modelDir,
}) {
  return Isolate.run(() {
    sherpa.initBindings();

    final recognizer = sherpa.OnlineRecognizer(
      sherpa.OnlineRecognizerConfig(
        model: sherpa.OnlineModelConfig(
          transducer: sherpa.OnlineTransducerModelConfig(
            encoder: '$modelDir/encoder-epoch-99-avg-1.int8.onnx',
            decoder: '$modelDir/decoder-epoch-99-avg-1.onnx',
            joiner: '$modelDir/joiner-epoch-99-avg-1.int8.onnx',
          ),
          tokens: '$modelDir/tokens.txt',
          numThreads: 2,
          debug: false,
          modelType: 'zipformer',
        ),
      ),
    );
    final stream = recognizer.createStream();
    try {
      final wave = sherpa.readWave(wavPath);
      stream.acceptWaveform(
        samples: wave.samples,
        sampleRate: wave.sampleRate,
      );
      // Flush the encoder with trailing silence so the tail decodes.
      stream.acceptWaveform(
        samples: Float32List(wave.sampleRate ~/ 2),
        sampleRate: wave.sampleRate,
      );
      stream.inputFinished();
      while (recognizer.isReady(stream)) {
        recognizer.decode(stream);
      }
      return recognizer.getResult(stream).text.trim();
    } finally {
      stream.free();
      recognizer.free();
    }
  });
}
