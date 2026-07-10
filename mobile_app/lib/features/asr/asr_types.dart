/// Pure, platform-agnostic types for the on-device dictation model.
///
/// Shared by the native implementation ([asr_manager_native.dart]) and the web
/// stub ([asr_manager_web.dart]) so both expose the same public API without
/// duplicating these definitions.
library;

enum AsrInstallState { notInstalled, downloading, extracting, installed, error }

class AsrStatus {
  final AsrInstallState state;
  final double progress; // 0..1 while downloading
  final String? error;

  const AsrStatus(this.state, {this.progress = 0, this.error});

  static const notInstalled = AsrStatus(AsrInstallState.notInstalled);
  static const installed = AsrStatus(AsrInstallState.installed);

  bool get isInstalled => state == AsrInstallState.installed;
  bool get isBusy =>
      state == AsrInstallState.downloading ||
      state == AsrInstallState.extracting;
}

/// Approximate download size of the dictation model, shown in the UI.
const int kAsrDownloadMB = 122;
