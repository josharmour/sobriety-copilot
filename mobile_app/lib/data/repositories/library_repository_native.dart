import 'dart:convert';
import 'package:flutter/foundation.dart' show kDebugMode, debugPrint;
import 'dart:io';
import 'package:archive/archive.dart';
import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite/sqflite.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart' show databaseFactoryFfi;

import 'package:sobriety_copilot_mobile/data/repositories/library_models.dart';

class LibraryRepository {
  final http.Client client;
  final SharedPreferences prefs;
  final String Function() baseUrl;

  LibraryRepository({
    required this.client,
    required this.prefs,
    required this.baseUrl,
  });

  static const String _prefPackVersion = 'lib_pack_version';
  static const String _prefPackDocCount = 'lib_pack_doc_count';
  
  Database? _db;

  Future<String> get _manifestsDir async {
    final docDir = await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(docDir.path, 'manifests'));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir.path;
  }

  Future<String> get _dbPath async {
    final dbDir = await getDatabasesPath();
    return p.join(dbDir, 'offline_search.db');
  }

  /// Directory holding the precomputed EmbeddingGemma vectors (v2+ packs).
  Future<String> get _vectorsDir async {
    final docDir = await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(docDir.path, 'vectors'));
    if (!await dir.exists()) await dir.create(recursive: true);
    return dir.path;
  }

  /// Paths to the shipped vector blob + row index if the installed pack
  /// carries them (v2+), else null. Aligned: idx line N ↔ blob row N.
  Future<({String blob, String idx, String meta})?> vectorFiles() async {
    final dir = await _vectorsDir;
    final blob = File(p.join(dir, 'vectors.i8'));
    final idx = File(p.join(dir, 'vectors.idx'));
    final meta = File(p.join(dir, 'vectors.meta.json'));
    if (await blob.exists() && await idx.exists() && await meta.exists()) {
      return (blob: blob.path, idx: idx.path, meta: meta.path);
    }
    return null;
  }

  int get localPackVersion => prefs.getInt(_prefPackVersion) ?? 0;
  int get localPackDocCount => prefs.getInt(_prefPackDocCount) ?? 0;

  Future<bool> get isPackInstalled async {
    if (localPackVersion <= 0) return false;
    final file = File(await _dbPath);
    return await file.exists();
  }

  /// Query server for the latest pack info
  Future<Map<String, dynamic>?> checkLatestPack() async {
    final uri = Uri.parse('${baseUrl()}/api/packs/latest');
    try {
      final res = await client.get(uri).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {
      // offline or server error
    }
    return null;
  }

  /// Download and install the pack version
  Future<void> downloadAndInstallPack(int version, String expectedSha256, {Function(double)? onProgress}) async {
    final url = '${baseUrl()}/api/packs/download/v$version';
    final tempDir = await getTemporaryDirectory();
    final tempFile = File(p.join(tempDir.path, 'download-v$version.scpack'));
    if (!await tempFile.parent.exists()) {
      await tempFile.parent.create(recursive: true);
    }
    if (await tempFile.exists()) {
      await tempFile.delete();
    }

    // Download stream to show progress
    final request = http.Request('GET', Uri.parse(url));
    final response = await client.send(request).timeout(const Duration(minutes: 5));
    
    if (response.statusCode != 200) {
      throw Exception('Failed to download pack: HTTP ${response.statusCode}');
    }

    final contentLength = response.contentLength ?? 0;
    int downloaded = 0;
    final sink = tempFile.openWrite();

    await for (final chunk in response.stream) {
      sink.add(chunk);
      downloaded += chunk.length;
      if (contentLength > 0 && onProgress != null) {
        onProgress(downloaded / contentLength);
      }
    }
    await sink.close();

    // Verify SHA256 (streaming)
    final hash = expectedSha256.isEmpty ? '' : expectedSha256.toLowerCase();
    if (expectedSha256.isNotEmpty) {
      final input = tempFile.openRead();
      final computedHash = (await sha256.bind(input).first).toString().toLowerCase();
      if (computedHash != hash) {
        await tempFile.delete();
        throw Exception('Pack verification failed: SHA256 mismatch');
      }
    }

    // Close existing DB connection if any
    await closeDb();

    final dbDestPath = await _dbPath;
    final dbFile = File(dbDestPath);
    if (!await dbFile.parent.exists()) {
      await dbFile.parent.create(recursive: true);
    }

    final mDir = await _manifestsDir;
    final vDir = await _vectorsDir;

    // Remove old manifests + vectors so a downgrade to a no-vectors pack
    // doesn't leave stale semantic data behind.
    for (final d in [Directory(mDir), Directory(vDir)]) {
      if (await d.exists()) {
        await d.delete(recursive: true);
      }
      await d.create(recursive: true);
    }

    int docCount = 0;

    // Extract archive (streaming to disk to prevent OOM on large files)
    final inputStream = InputFileStream(tempFile.path);
    final archive = ZipDecoder().decodeStream(inputStream);

    for (final file in archive) {
      if (file.isFile) {
        if (file.name == 'pack.json') {
          final data = file.content as List<int>;
          final meta = jsonDecode(utf8.decode(data)) as Map<String, dynamic>;
          docCount = meta['doc_count'] as int? ?? 0;
        } else {
          String outPath;
          if (file.name == 'manifest-index.json') {
            outPath = p.join(mDir, 'manifest-index.json');
          } else if (file.name == 'search.db') {
            outPath = dbDestPath;
          } else if (file.name.startsWith('manifests/')) {
            outPath = p.join(mDir, file.name.substring('manifests/'.length));
          } else if (file.name.startsWith('vectors/') ||
              file.name.startsWith('vectors.')) {
            final vName = file.name.contains('/')
                ? file.name.substring(file.name.indexOf('/') + 1)
                : file.name;
            outPath = p.join(vDir, vName);
          } else {
            continue;
          }
          final outStream = OutputFileStream(outPath);
          file.writeContent(outStream);
          outStream.close();
        }
      }
    }
    
    inputStream.close();

    // Clean up temp file
    if (await tempFile.exists()) {
      await tempFile.delete();
    }

    // Update preferences
    await prefs.setInt(_prefPackVersion, version);
    await prefs.setInt(_prefPackDocCount, docCount);
  }

  /// Open/initialize the SQLite database connection.
  ///
  /// Opened through the FFI factory on purpose: the pack's index is FTS5 and
  /// Android's platform SQLite ships without the fts5 module ("no such
  /// module: fts5"), so the bundled SQLite (sqlite3_flutter_libs) must serve
  /// this database on every platform.
  Future<Database> get _database async {
    if (_db != null && _db!.isOpen) return _db!;
    final path = await _dbPath;
    _db = await databaseFactoryFfi.openDatabase(
      path,
      options: OpenDatabaseOptions(readOnly: true),
    );
    return _db!;
  }

  Future<void> closeDb() async {
    if (_db != null && _db!.isOpen) {
      await _db!.close();
      _db = null;
    }
  }

  /// Browse list of books offline
  Future<List<OfflineBookIndex>> getBooks() async {
    final mDir = await _manifestsDir;
    final indexFile = File(p.join(mDir, 'manifest-index.json'));
    if (!await indexFile.exists()) return [];
    try {
      final data = await indexFile.readAsString();
      final list = jsonDecode(data) as List<dynamic>;
      return list.map((e) => OfflineBookIndex.fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {
      return [];
    }
  }

  /// Load a document manifest offline
  Future<Map<String, dynamic>?> getManifest(String docId) async {
    final mDir = await _manifestsDir;
    final mFile = File(p.join(mDir, '$docId.json'));
    if (!await mFile.exists()) return null;
    try {
      final data = await mFile.readAsString();
      return jsonDecode(data) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  /// FTS5 Search offline using SQLite BM25
  Future<List<OfflineSearchResult>> search(String query) async {
    if (!await isPackInstalled) return [];
    try {
      final db = await _database;
      final List<Map<String, dynamic>> rows = await db.rawQuery(
        'SELECT doc_id, block_id, heading, text FROM blocks WHERE blocks MATCH ? ORDER BY rank LIMIT 30',
        [query]
      );
      return rows.map((r) => OfflineSearchResult(
        docId: r['doc_id'] as String? ?? '',
        blockId: r['block_id'] as String? ?? '',
        heading: r['heading'] as String? ?? '',
        text: r['text'] as String? ?? '',
      )).toList();
    } catch (e) {
      if (kDebugMode) debugPrint('[LibrarySearch] query failed: $e');
      return [];
    }
  }

  /// Fetches a single block's heading + text by id (for vector hits, which
  /// carry only doc_id/block_id). Linear scan on the FTS table, but only a
  /// handful of lookups per query.
  Future<OfflineSearchResult?> getBlock(String docId, String blockId) async {
    if (!await isPackInstalled) return null;
    try {
      final db = await _database;
      final rows = await db.rawQuery(
        'SELECT doc_id, block_id, heading, text FROM blocks '
        'WHERE doc_id = ? AND block_id = ? LIMIT 1',
        [docId, blockId],
      );
      if (rows.isEmpty) return null;
      final r = rows.first;
      return OfflineSearchResult(
        docId: r['doc_id'] as String? ?? '',
        blockId: r['block_id'] as String? ?? '',
        heading: r['heading'] as String? ?? '',
        text: r['text'] as String? ?? '',
      );
    } catch (e) {
      if (kDebugMode) debugPrint('[LibrarySearch] getBlock failed: $e');
      return null;
    }
  }
}
