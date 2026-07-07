/// Conditional implementation selector for reminder scheduling.
library;

export 'reminders_native.dart'
    if (dart.library.js_interop) 'reminders_stub.dart';
