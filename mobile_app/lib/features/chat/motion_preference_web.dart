import 'dart:js_interop';

import 'package:flutter/foundation.dart';
@JS('window.matchMedia')
external _MotionQuery _matchMedia(String query);

extension type _MotionQuery(JSObject _) implements JSObject {
  external bool get matches;
  external void addEventListener(String type, JSFunction listener);
  external void removeEventListener(String type, JSFunction listener);
}

// Flutter 3.41's web engine does not expose prefers-reduced-motion through
// MediaQuery. Keep the browser preference live, including mid-session changes.
ValueNotifier<bool> createMotionPreference() => _BrowserMotionPreference(
  _matchMedia('(prefers-reduced-motion: reduce)'),
);

class _BrowserMotionPreference extends ValueNotifier<bool> {
  _BrowserMotionPreference(this._query) : super(_query.matches) {
    _listener = ((JSAny? _) {
      value = _query.matches;
    }).toJS;
    _query.addEventListener('change', _listener);
  }

  final _MotionQuery _query;
  late final JSFunction _listener;

  @override
  void dispose() {
    _query.removeEventListener('change', _listener);
    super.dispose();
  }
}
