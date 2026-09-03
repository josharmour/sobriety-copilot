// On-device WAV transcription. Resolves to the sherpa-onnx implementation on
// native platforms and to a throwing stub on web (dictation is native-only —
// see capabilities.dart), so the web build never compiles sherpa_onnx.
export 'asr_service_native.dart'
    if (dart.library.js_interop) 'asr_service_web.dart';
