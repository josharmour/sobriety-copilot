import 'dart:io';

import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// On Windows/Linux, route sqflite through the FFI factory — the stock
/// sqflite plugin is mobile-only, and without this the offline library
/// (packs, FTS search, reader) crashes at runtime on desktop.
void initPlatform() {
  if (Platform.isWindows || Platform.isLinux) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
}
