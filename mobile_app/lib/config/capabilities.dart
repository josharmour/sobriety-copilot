import 'package:flutter/foundation.dart';

/// Per-surface capability flags so shared UI can hide affordances that a
/// platform's plugins can't back (instead of failing with runtime snackbars).
bool get _isMobile =>
    !kIsWeb &&
    (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS);

/// Camera capture + on-device OCR (google_mlkit, image_picker camera) —
/// mobile-only plugins.
bool get supportsCameraAndOcr => _isMobile;

/// Mic dictation (record plugin + dart:io temp files → /api/transcribe).
bool get supportsMicInput => _isMobile;
