// On-device dictation model lifecycle. Resolves to the native (sherpa-onnx /
// dart:io) implementation on Android/iOS and to a no-op stub on web, so the
// web build compiles without native-only libraries. Both variants re-export
// asr_types.dart, so importers keep seeing AsrStatus / AsrInstallState /
// kAsrDownloadMB.
export 'asr_manager_native.dart'
    if (dart.library.js_interop) 'asr_manager_web.dart';
