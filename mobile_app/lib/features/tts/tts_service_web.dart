import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_tts/flutter_tts.dart';

class AppTts {
  AppTts(this._ref) {
    _system.setCompletionHandler(() => onDone?.call());
    _system.setCancelHandler(() {});
    _system.setErrorHandler((_) => onDone?.call());
  }

  final Ref _ref;
  final FlutterTts _system = FlutterTts();

  void Function()? onDone;

  Future<void> speak(String text) async {
    await stop();
    await _system.speak(text);
  }

  Future<void> stop() async {
    await _system.stop();
  }

  void dispose() {
    _system.stop();
  }
}
