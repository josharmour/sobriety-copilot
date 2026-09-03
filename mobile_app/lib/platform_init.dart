/// Startup platform bootstrap (conditional): desktop needs the sqflite FFI
/// database factory so the offline library works there too; web is a no-op.
library;

export 'platform_init_native.dart'
    if (dart.library.js_interop) 'platform_init_web.dart';
