import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'asr_types.dart';

// Keep the shared types visible to importers of asr_manager.dart on web too.
export 'asr_types.dart';

/// Web build: on-device dictation is native-only (the mic UI is gated to
/// Android/iOS in capabilities.dart, so this is never surfaced). This stub
/// keeps the same public API as [asr_manager_native.dart] so the web app
/// compiles without dart:io / sherpa_onnx.
class AsrManagerNotifier extends Notifier<AsrStatus> {
  @override
  AsrStatus build() => AsrStatus.notInstalled;

  Future<void> download() async {
    state = const AsrStatus(
      AsrInstallState.error,
      error: 'On-device dictation is not available on the web.',
    );
  }

  Future<void> delete() async {
    state = AsrStatus.notInstalled;
  }

  String? installedDir() => null;
}

final asrManagerProvider =
    NotifierProvider<AsrManagerNotifier, AsrStatus>(AsrManagerNotifier.new);
