import 'dart:io';

import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Native SQLite bootstrap.
///
/// - Windows/Linux: stock sqflite is mobile-only — route everything through
///   the FFI factory (bundled SQLite) or the offline library crashes.
/// - Android/iOS: the FFI loader is initialized so the library repository can
///   open its FTS5 search index with the BUNDLED SQLite (sqlite3_flutter_libs)
///   — Android's platform SQLite lacks the fts5 module, which silently broke
///   all offline search. The global factory stays on the platform plugin.
void initPlatform() {
  sqfliteFfiInit();
  if (Platform.isWindows || Platform.isLinux) {
    databaseFactory = databaseFactoryFfi;
  }
}
