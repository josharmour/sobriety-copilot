/// Home-screen widget bridge for the sobriety tracker.
///
/// Native (Android/iOS) pushes the sobriety date into the platform widget
/// store via home_widget; web (and unsupported desktops, guarded at runtime)
/// is a no-op so shared code can call this unconditionally.
library;

export 'widget_sync_native.dart'
    if (dart.library.js_interop) 'widget_sync_stub.dart';
