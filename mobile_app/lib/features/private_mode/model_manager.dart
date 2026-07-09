import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// The on-device model for Private Mode.
///
/// Gemma 4 E2B instruction-tuned, `.litertlm` (mixed 2/4/8-bit QAT).
/// Apache-2.0, ungated on the Hugging Face CDN (verified 2026-07-07), loaded
/// by flutter_gemma's LiteRT-LM engine on Android. The file is downloaded to
/// app-support storage and used in place — same pattern as the neural TTS
/// voices in features/tts/voice_manager.dart.
const String kPrivateModelName = 'Gemma 4 E2B';
const String kPrivateModelFile = 'gemma-4-E2B-it.litertlm';
const String kPrivateModelUrl =
    'https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm';
const int kPrivateModelBytes = 2588147712; // exact size, used to verify

// NOTE: the Tensor-G5 NPU build (gemma-4-E2B-it_Google_Tensor_G5.litertlm)
// is NOT supported: its tf_lite_mtp_aux component hard-aborts the LiteRT
// runtime bundled with flutter_gemma 0.13.6. Revisit on a newer runtime.

/// Private Mode is Android-only for now: the plugin's mobile engines are
/// battle-tested there; desktop runs a JVM sidecar we haven't validated and
/// web can't hold a 2.6 GB model.
bool get privateModeSupported =>
    !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

enum PrivateModelPhase { notInstalled, downloading, installed, error }

class PrivateModelState {
  final PrivateModelPhase phase;
  final double progress; // 0..1 while downloading
  final String? error;

  const PrivateModelState(this.phase, {this.progress = 0, this.error});

  bool get isInstalled => phase == PrivateModelPhase.installed;
  bool get isDownloading => phase == PrivateModelPhase.downloading;
}

/// Owns the model file lifecycle: download with resume, verify, delete.
///
/// ## Download architecture
///
/// Hugging Face's URL redirects to a **Xet CDN signed URL** with a limited
/// expiry.  The Dart `http` package's `IOClient` strips the `Range` header
/// when following cross-origin redirects, and a stale signed URL returns 403.
///
/// To work around both, this notifier:
///
///  1. Resolves the redirect chain with a HEAD request to get a *fresh*
///     signed CDN URL before every download attempt.
///  2. Sends the GET/Range request **directly** to the CDN URL — no
///     cross-origin redirect to strip headers.
///  3. Preserves the `.part` file on transient errors so a subsequent
///     `retry()` can resume where it left off.
///  4. Handles 403 (expired URL) by re-resolving and retrying
///     automatically, with a bounded attempt count.
class PrivateModelNotifier extends Notifier<PrivateModelState> {
  http.Client? _downloadClient;
  bool _cancelRequested = false;

  /// Test seam: override to inject a mock [http.Client].  Defaults to
  /// constructing a real client when null.
  http.Client Function()? clientFactory;

  /// Test seam: override to use a different expected model size.
  /// Defaults to [kPrivateModelBytes].
  int expectedBytes = kPrivateModelBytes;

  /// Test seam: override to point at a test server instead of HF.
  /// Defaults to [kPrivateModelUrl].
  String modelUrl = kPrivateModelUrl;

  @override
  PrivateModelState build() {
    if (!privateModeSupported) {
      return const PrivateModelState(PrivateModelPhase.notInstalled);
    }
    // Async existence probe; state flips to installed shortly after startup
    // if the file is already there and complete.
    _probe();
    return const PrivateModelState(PrivateModelPhase.notInstalled);
  }

  /// Download target (app-support storage).
  static Future<String> modelPath() async {
    final dir = await getApplicationSupportDirectory();
    return p.join(dir.path, 'private_model', kPrivateModelFile);
  }

  /// Finds a complete model file in either supported location: the in-app
  /// download target, or the app's external-files dir (sideload target —
  /// `adb push <file> /sdcard/Android/data/<pkg>/files/` for testing).
  static Future<File?> resolveModelFile(
      {int expectedBytes = kPrivateModelBytes}) async {
    final candidates = <(String, int)>[(await modelPath(), expectedBytes)];
    try {
      final ext = await getExternalStorageDirectory();
      if (ext != null) {
        candidates.add((
          p.join(ext.path, kPrivateModelFile),
          expectedBytes,
        ));
      }
    } catch (_) {
      // External storage unavailable; only the download target applies.
    }
    for (final (path, bytes) in candidates) {
      final file = File(path);
      try {
        if (await file.exists() && await file.length() == bytes) {
          return file;
        }
      } catch (_) {}
    }
    return null;
  }

  Future<void> _probe() async {
    try {
      if (await resolveModelFile(expectedBytes: expectedBytes) != null) {
        state = const PrivateModelState(PrivateModelPhase.installed);
      }
    } catch (_) {
      // Leave as notInstalled.
    }
  }

  /// Re-check the filesystem (e.g. after a sideload while the app was open).
  Future<void> refresh() => _probe();

  /// Resolves the Hugging Face URL through its redirect chain and returns
  /// the final signed CDN URL.  Every call issues a new HEAD request so the
  /// returned URL has a fresh expiry window.
  ///
  /// In http 1.6.0, [IOClient.send] returns `_IOStreamedResponseV2` which
  /// implements [http.BaseResponseWithUrl].  The `url` on that interface
  /// is set from `response.redirects.last.location` (the post-redirect URL)
  /// by IOClient — see io_client.dart:219-221.
  Future<Uri> _resolveSignedUrl(http.Client client) async {
    final headReq = http.Request('HEAD', Uri.parse(modelUrl));
    final headRes = await client
        .send(headReq)
        .timeout(const Duration(seconds: 30));

    await headRes.stream.drain();

    if (headRes.statusCode < 200 || headRes.statusCode >= 300) {
      throw Exception('HEAD request failed with HTTP ${headRes.statusCode}');
    }

    // Pattern-match on BaseResponseWithUrl to extract the post-redirect URL.
    // IOClient returns _IOStreamedResponseV2 which implements this interface.
    if (headRes case http.BaseResponseWithUrl(:final url)) {
      return url;
    }

    // Fallback for non-IO clients (e.g. test mocks that don't follow
    // redirects).
    return Uri.parse(modelUrl);
  }

  Future<void> download() async {
    if (state.isDownloading) return;
    _cancelRequested = false;
    state = const PrivateModelState(PrivateModelPhase.downloading);

    final path = await modelPath();
    final file = File(path);
    final tmp = File('$path.part');
    await tmp.parent.create(recursive: true);

    final client = clientFactory?.call() ?? http.Client();
    _downloadClient = client;
    IOSink? sink;

    try {
      // Bound total attempts to avoid infinite loops (403/416 cycles).
      var attempts = 0;
      const maxAttempts = 5;

      // 1. Resolve the signed CDN URL fresh — never reuse a stale URL.
      var signedUrl = await _resolveSignedUrl(client);

      // 2. Check for an existing partial download (e.g. from a prior failure).
      var existingBytes = 0;
      if (await tmp.exists()) {
        existingBytes = await tmp.length();
        if (existingBytes >= expectedBytes) {
          if (existingBytes == expectedBytes) {
            // Completed part that wasn't renamed yet — promote to final.
            if (await file.exists()) await file.delete();
            await tmp.rename(file.path);
            state = const PrivateModelState(PrivateModelPhase.installed);
            return;
          }
          // Oversized / mismatched .part — discard and restart from zero.
          await tmp.delete();
          existingBytes = 0;
        }
      }

      // 3. Download loop — may re-resolve on 403/416.
      while (attempts < maxAttempts) {
        attempts++;
        final req = http.Request('GET', signedUrl);
        if (existingBytes > 0) {
          req.headers['Range'] = 'bytes=$existingBytes-';
        }

        var res = await client.send(req);

        // 3a. 403 → signed URL expired; re-resolve and retry.
        if (res.statusCode == 403) {
          await res.stream.drain();
          signedUrl = await _resolveSignedUrl(client);
          continue;
        }

        // 3b. 416 → range not satisfiable; restart from zero, re-resolve.
        if (res.statusCode == 416) {
          await res.stream.drain();
          existingBytes = 0;
          signedUrl = await _resolveSignedUrl(client);
          continue;
        }

        // 3c. Any other error status → fail.
        if (res.statusCode < 200 || res.statusCode >= 300) {
          await res.stream.drain();
          throw Exception('HTTP ${res.statusCode}');
        }

        // 3d. 200 on a Range request → server ignored Range; restart.
        final isPartial = res.statusCode == 206;
        if (!isPartial && existingBytes > 0) {
          existingBytes = 0;
        }

        // 4. Stream the response body to the .part file.
        final total = isPartial
            ? (res.contentLength ?? (expectedBytes - existingBytes)) +
                existingBytes
            : (res.contentLength ?? expectedBytes);

        var received = existingBytes;
        var lastEmit = received;
        sink = tmp.openWrite(
            mode: isPartial ? FileMode.append : FileMode.write);

        await for (final chunk in res.stream) {
          if (_cancelRequested) throw const _CancelledDownload();
          sink.add(chunk);
          received += chunk.length;
          // Throttle state updates to ~every 8 MB.
          if (received - lastEmit > 8 * 1024 * 1024) {
            lastEmit = received;
            state = PrivateModelState(
              PrivateModelPhase.downloading,
              progress: received / total,
            );
          }
        }
        await sink.flush();
        await sink.close();
        sink = null;

        // 5. Integrity check: verify the expected file size.
        final size = await tmp.length();
        if (size != expectedBytes) {
          throw Exception(
            'Download incomplete ($size of $expectedBytes bytes)',
          );
        }

        // 6. Rename .part → final file.
        if (await file.exists()) await file.delete();
        await tmp.rename(file.path);
        state = const PrivateModelState(PrivateModelPhase.installed);
        return; // Success!
      }

      throw Exception('Download failed after $maxAttempts attempts');
    } on _CancelledDownload {
      // Explicit cancellation — .part is cleaned up in `finally` below.
      state = const PrivateModelState(PrivateModelPhase.notInstalled);
    } catch (e) {
      // Transient error: preserve .part so retry() can resume.
      state = _cancelRequested
          ? const PrivateModelState(PrivateModelPhase.notInstalled)
          : PrivateModelState(PrivateModelPhase.error, error: e.toString());
    } finally {
      try {
        await sink?.close();
      } catch (_) {}
      // Only clean up .part on explicit cancellation, not on transient errors.
      if (_cancelRequested) {
        try {
          if (await tmp.exists()) await tmp.delete();
        } catch (_) {}
      }
      client.close();
      // Guard: only null _downloadClient if it still refers to this client.
      // A slow finally from a cancelled download should not clobber a
      // newly started download's client.
      if (identical(_downloadClient, client)) _downloadClient = null;
    }
  }

  /// Cancel an in-flight download.  Cleans up the partial file.
  void cancelDownload() {
    _cancelRequested = true;
    // Closing the client aborts the in-flight response stream promptly.
    _downloadClient?.close();
  }

  /// Retry a failed download, preserving any partial progress (.part file).
  /// Falls through to [download] which resumes from the existing .part data.
  Future<void> retry() => download();

  Future<void> delete() async {
    try {
      final file = await resolveModelFile(expectedBytes: expectedBytes);
      if (file != null) await file.delete();
    } catch (_) {}
    state = const PrivateModelState(PrivateModelPhase.notInstalled);
  }
}

class _CancelledDownload implements Exception {
  const _CancelledDownload();
}

final privateModelProvider =
    NotifierProvider<PrivateModelNotifier, PrivateModelState>(
  PrivateModelNotifier.new,
);
