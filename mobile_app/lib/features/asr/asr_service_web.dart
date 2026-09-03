/// Web build: there is no on-device ASR — dictation is native-only (the mic UI
/// is gated to Android/iOS in capabilities.dart). This stub exists so the web
/// app compiles without pulling in sherpa_onnx (which needs dart:ffi). It is
/// never invoked on web.
Future<String> transcribeWavFile({
  required String wavPath,
  required String modelDir,
}) async =>
    throw UnsupportedError('On-device dictation is not available on the web.');
