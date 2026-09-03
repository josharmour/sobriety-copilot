import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/private_mode/model_manager.dart';

/// Small model size for tests — exercises the full download pipeline quickly.
const int _testModelSize = 64 * 1024; // 64 KB

// ── PathProvider stub ────────────────────────────────────────────────────────

class _FakePathProvider extends PathProviderPlatform
    with MockPlatformInterfaceMixin {
  final String tmpDir;
  _FakePathProvider(this.tmpDir);

  @override
  Future<String> getApplicationSupportPath() async =>
      p.join(tmpDir, 'support');

  @override
  Future<String> getTemporaryPath() async => p.join(tmpDir, 'tmp');
}

// ── Test HTTP server (real dart:io) ─────────────────────────────────────────

/// Records what the test server observed.
class ServerState {
  int headCalls = 0;
  int getCalls = 0;
  final rangeHeadersReceived = <String?>[];

  /// First resume GET returns 403 (expired URL). Only triggers when the
  /// request includes a Range header with start > 0.
  bool expireOnce = false;
  bool _expiredConsumed = false;

  /// CDN ignores Range, always returns 200.
  bool ignoreRange = false;

  /// First Range GET returns 416.
  bool return416 = false;
  bool _status416Consumed = false;

  /// If non-null, the first Range-resume GET closes the response after
  /// writing this many bytes (no Content-Length set).  The client sees
  /// fewer bytes than expected and the integrity check fails.
  int? cutAfterBytes;

  /// Delay (ms) before the CDN GET response body begins streaming.
  /// Used by the cancel test to ensure the download is still in-flight.
  int responseDelayMs = 0;

  int fileSize = _testModelSize;
}

/// A running test server bound to 127.0.0.1.
class TestServer {
  final HttpServer _server;
  final String baseUrl;
  final ServerState state;
  TestServer(this._server, this.baseUrl, this.state);

  Uri get resolveUrl => Uri.parse('$baseUrl/resolve');
  Future<void> stop() => _server.close(force: true);
}

/// Starts a test server that simulates HF → CDN redirect + CDN download.
///
///   /resolve  → 302 Location: /cdn
///   /cdn      → configured behaviour based on [state]
///
Future<TestServer> startTestServer(ServerState state) async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  final baseUrl = 'http://${server.address.host}:${server.port}';
  final cdnUrl = '$baseUrl/cdn';

  server.listen((HttpRequest request) async {
    final uri = request.uri;

    // ── Redirect endpoint ─────────────────────────────────────────────────
    if (uri.path == '/resolve') {
      request.response.statusCode = 302;
      request.response.headers.set('location', cdnUrl);
      await request.drain<void>(null);
      await request.response.close();
      return;
    }

    // ── CDN endpoint ──────────────────────────────────────────────────────
    if (uri.path == '/cdn') {
      if (request.method == 'HEAD') {
        state.headCalls++;
        await request.drain<void>(null);
        request.response.statusCode = 200;
        request.response.headers.contentLength = state.fileSize;
        await request.response.close();
        return;
      }

      // GET
      state.getCalls++;
      final rangeHeader = request.headers.value('range');
      state.rangeHeadersReceived.add(rangeHeader);

      final match = rangeHeader == null
          ? null
          : RegExp(r'bytes=(\d+)-').firstMatch(rangeHeader);
      final start = match == null ? 0 : int.parse(match.group(1)!);
      final hasRange = rangeHeader != null;

      // Expired URL (first resume).
      if (state.expireOnce && hasRange && start > 0 && !state._expiredConsumed) {
        state._expiredConsumed = true;
        await request.drain<void>(null);
        request.response.statusCode = 403;
        await request.response.close();
        return;
      }

      // 416 (first Range request).
      if (state.return416 && hasRange && !state._status416Consumed) {
        state._status416Consumed = true;
        await request.drain<void>(null);
        request.response.statusCode = 416;
        await request.response.close();
        return;
      }

      final effectiveStart = state.ignoreRange ? 0 : start;
      final remaining = state.fileSize - effectiveStart;

      if (remaining <= 0) {
        await request.drain<void>(null);
        request.response.statusCode = 416;
        await request.response.close();
        return;
      }

      // Response delay (for cancel test — keep the download in-flight).
      if (state.responseDelayMs > 0) {
        await Future.delayed(Duration(milliseconds: state.responseDelayMs));
      }

      // Mid-stream truncation on Range resume (no Content-Length set, so
      // the client sees end-of-stream early and the integrity check fails).
      if (state.cutAfterBytes != null && hasRange && start > 0 && remaining > 0) {
        final isPartial = effectiveStart > 0;
        request.response.statusCode = isPartial ? 206 : 200;
        request.response.headers.set('accept-ranges', 'bytes');
        try {
          request.response.add(List.filled(state.cutAfterBytes!, 0x42));
          await request.response.flush();
        } catch (_) {}
        // No Content-Length — the response ends here without error.
        // The client stream ends, and the integrity check will fail.
        await request.response.close();
        return;
      }

      // Normal response.
      final isPartial = effectiveStart > 0 && !state.ignoreRange;
      request.response.statusCode = isPartial ? 206 : 200;
      if (isPartial) {
        request.response.headers.set(
          'content-range',
          'bytes $effectiveStart-${state.fileSize - 1}/${state.fileSize}',
        );
      }
      request.response.contentLength = remaining;

      try {
        request.response.add(List.filled(remaining, 0x42));
        await request.response.close();
      } catch (_) {
        // Client may have disconnected.
      }
      return;
    }

    await request.drain<void>(null);
    request.response.statusCode = 404;
    await request.response.close();
  });

  return TestServer(server, baseUrl, state);
}

// ── Test container factory ──────────────────────────────────────────────────

ProviderContainer _makeContainer(
  TestServer server,
  String tmpDir, {
  int expectedBytes = _testModelSize,
}) {
  return ProviderContainer(overrides: [
    privateModelProvider.overrideWith(() {
      final n = PrivateModelNotifier();
      n.clientFactory = () => http.Client();
      n.expectedBytes = expectedBytes;
      n.modelUrl = server.resolveUrl.toString();
      return n;
    }),
  ]);
}

// ── Helpers ─────────────────────────────────────────────────────────────────

String _setupTempDir() {
  final tmp = Directory.systemTemp.createTempSync('model_mgr_test_');
  PathProviderPlatform.instance = _FakePathProvider(tmp.path);
  return tmp.path;
}

File _partFile(String tmpDir) {
  return File(p.join(
      tmpDir, 'support', 'private_model', '$kPrivateModelFile.part'));
}

File _modelFile(String tmpDir) {
  return File(p.join(
      tmpDir, 'support', 'private_model', kPrivateModelFile));
}

// ── Tests ───────────────────────────────────────────────────────────────────

void main() {
  late String tmpDir;

  setUp(() {
    tmpDir = _setupTempDir();
  });

  tearDown(() {
    if (tmpDir.isNotEmpty) {
      Directory(tmpDir).deleteSync(recursive: true);
    }
  });

  group('resolveModelFile', () {
    test('returns null when no file exists', () async {
      final f = await PrivateModelNotifier.resolveModelFile();
      expect(f, isNull);
    });

    test('finds a correctly-sized file', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      final f = _modelFile(tmpDir);
      final raf = await f.open(mode: FileMode.write);
      await raf.truncate(_testModelSize);
      await raf.close();
      final resolved = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(resolved, isNotNull);
      expect(resolved!.path, f.path);
    });
  });

  group('download (real HttpServer)', () {
    test('full download succeeds and transitions to installed', () async {
      final state = ServerState();
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);
      expect(state.getCalls, greaterThanOrEqualTo(1));
      expect(state.headCalls, greaterThanOrEqualTo(1));

      container.dispose();
      await server.stop();
    });

    test('Range header reaches CDN on resume', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      await _partFile(tmpDir).writeAsBytes(List.filled(1000, 0x41));

      final state = ServerState();
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      expect(
        state.rangeHeadersReceived.any(
            (h) => h != null && h.startsWith('bytes=')),
        isTrue,
        reason: 'Range header should be present on resume GET',
      );

      container.dispose();
      await server.stop();
    });

    test('resume transfers fewer bytes than full size', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      final half = _testModelSize ~/ 2;
      await _partFile(tmpDir).writeAsBytes(List.filled(half, 0x41));

      final state = ServerState();
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);

      container.dispose();
      await server.stop();
    });

    test('403 expired resume triggers second HEAD and succeeds', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      final half = _testModelSize ~/ 2;
      await _partFile(tmpDir).writeAsBytes(List.filled(half, 0x41));

      final state = ServerState()..expireOnce = true;
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      expect(state.headCalls, greaterThanOrEqualTo(2),
          reason: '403 expiry should trigger a second HEAD');
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);

      container.dispose();
      await server.stop();
    });

    test('403 on first attempt also recovers', () async {
      // Custom server: first GET (even without Range) returns 403.
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final baseUrl = 'http://${server.address.host}:${server.port}';
      final cdnUrl = '$baseUrl/cdn';
      var firstGet = true;
      var headCount = 0;

      server.listen((HttpRequest request) async {
        if (request.uri.path == '/resolve') {
          request.response.statusCode = 302;
          request.response.headers.set('location', cdnUrl);
          await request.drain<void>(null);
          await request.response.close();
          return;
        }
        if (request.uri.path == '/cdn') {
          if (request.method == 'HEAD') {
            headCount++;
            await request.drain<void>(null);
            request.response.statusCode = 200;
            request.response.headers.contentLength = _testModelSize;
            await request.response.close();
            return;
          }
          if (firstGet) {
            firstGet = false;
            await request.drain<void>(null);
            request.response.statusCode = 403;
            await request.response.close();
            return;
          }
          await request.drain<void>(null);
          request.response.statusCode = 200;
          request.response.contentLength = _testModelSize;
          request.response.add(List.filled(_testModelSize, 0x42));
          await request.response.close();
          return;
        }
        await request.drain<void>(null);
        request.response.statusCode = 404;
        await request.response.close();
      });

      final container = ProviderContainer(overrides: [
        privateModelProvider.overrideWith(() {
          final n = PrivateModelNotifier();
          n.clientFactory = () => http.Client();
          n.expectedBytes = _testModelSize;
          n.modelUrl = '$baseUrl/resolve';
          return n;
        }),
      ]);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      expect(headCount, greaterThanOrEqualTo(2),
          reason: 'First-attempt 403 should trigger re-resolve');
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);

      container.dispose();
      await server.close(force: true);
    });

    test('200 instead of 206 restarts from zero', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      await _partFile(tmpDir).writeAsBytes(List.filled(1000, 0x41));

      final state = ServerState()..ignoreRange = true;
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);

      container.dispose();
      await server.stop();
    });

    test('416 on resume restarts from zero', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      await _partFile(tmpDir).writeAsBytes(List.filled(500, 0x41));

      final state = ServerState()..return416 = true;
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);

      container.dispose();
      await server.stop();
    });

    test('mid-stream socket error preserves .part for retry', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      await _partFile(tmpDir).writeAsBytes(List.filled(5000, 0x41));

      final state = ServerState()
        ..fileSize = _testModelSize * 10
        ..cutAfterBytes = 4096;
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.error);
      expect(await _partFile(tmpDir).exists(), isTrue,
          reason: '.part should survive mid-stream error');
      expect(await _partFile(tmpDir).length(), greaterThan(0));

      container.dispose();
      await server.stop();
    });

    test('retry completes after mid-stream error', () async {
      // Phase 1: partial download fails mid-stream.
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);

      final state1 = ServerState()
        ..fileSize = _testModelSize * 10
        ..cutAfterBytes = 4096;
      final server1 = await startTestServer(state1);
      final container1 = _makeContainer(server1, tmpDir);
      final notifier1 = container1.read(privateModelProvider.notifier);

      await notifier1.download();
      expect(notifier1.state.phase, PrivateModelPhase.error);
      expect(await _partFile(tmpDir).exists(), isTrue);
      final partialBytes = await _partFile(tmpDir).length();
      expect(partialBytes, greaterThan(0));

      container1.dispose();
      await server1.stop();

      // Phase 2: fresh notifier, fresh server — .part on disk.
      final state2 = ServerState();
      final server2 = await startTestServer(state2);
      final container2 = _makeContainer(server2, tmpDir);
      final notifier2 = container2.read(privateModelProvider.notifier);

      await notifier2.download();

      expect(notifier2.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize,
          reason: 'Retry should install correct full-size file');

      container2.dispose();
      await server2.stop();
    });

    test('cancel cleans up .part and reverts to notInstalled', () async {
      final state = ServerState()
        ..fileSize = _testModelSize * 50
        ..responseDelayMs = 300;
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      final fut = notifier.download();
      // Give it time to resolve the URL and enter the streaming phase.
      await Future.delayed(const Duration(milliseconds: 50));
      notifier.cancelDownload();
      await fut;

      expect(notifier.state.phase, PrivateModelPhase.notInstalled);
      expect(await _partFile(tmpDir).exists(), isFalse,
          reason: '.part should be cleaned up on cancel');

      container.dispose();
      await server.stop();
    });

    test('oversized .part is discarded and download restarts', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);

      // .part bigger than expected model size.
      await _partFile(tmpDir)
          .writeAsBytes(List.filled(_testModelSize + 1000, 0x41));

      final state = ServerState();
      final server = await startTestServer(state);
      final container = _makeContainer(server, tmpDir);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.download();

      expect(notifier.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize);

      container.dispose();
      await server.stop();
    });

    test('integrity failure does NOT install bad file on retry', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);

      // Phase 1: truncated response (half the expected size).
      final state1 = ServerState()..fileSize = _testModelSize ~/ 2;
      final server1 = await startTestServer(state1);
      final container1 = _makeContainer(server1, tmpDir,
          expectedBytes: _testModelSize);
      final notifier1 = container1.read(privateModelProvider.notifier);

      await notifier1.download();
      expect(notifier1.state.phase, PrivateModelPhase.error);
      expect(notifier1.state.error, contains('Download incomplete'));

      expect(await _partFile(tmpDir).exists(), isTrue);
      expect(await _partFile(tmpDir).length(), _testModelSize ~/ 2);

      container1.dispose();
      await server1.stop();

      // Phase 2: full-size server.
      final state2 = ServerState();
      final server2 = await startTestServer(state2);
      final container2 = _makeContainer(server2, tmpDir,
          expectedBytes: _testModelSize);
      final notifier2 = container2.read(privateModelProvider.notifier);

      await notifier2.download();

      expect(notifier2.state.phase, PrivateModelPhase.installed);
      final file = await PrivateModelNotifier.resolveModelFile(
          expectedBytes: _testModelSize);
      expect(file, isNotNull);
      expect(await file!.length(), _testModelSize,
          reason: 'Retry should install correct full-size file');

      container2.dispose();
      await server2.stop();
    });
  });

  group('delete', () {
    test('delete removes installed model and resets state', () async {
      final dir = Directory(p.join(tmpDir, 'support', 'private_model'));
      await dir.create(recursive: true);
      final f = _modelFile(tmpDir);
      final raf = await f.open(mode: FileMode.write);
      await raf.truncate(_testModelSize);
      await raf.close();

      final container = ProviderContainer(overrides: [
        privateModelProvider.overrideWith(() {
          final n = PrivateModelNotifier();
          n.expectedBytes = _testModelSize;
          return n;
        }),
      ]);
      final notifier = container.read(privateModelProvider.notifier);

      await notifier.refresh();
      expect(notifier.state.phase, PrivateModelPhase.installed);

      await notifier.delete();

      expect(notifier.state.phase, PrivateModelPhase.notInstalled);
      container.dispose();
    });
  });
}
