import 'dart:convert';
import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sobriety_copilot_mobile/features/tts/neural_voices.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Tone option shown in settings. Backend accepts the `id` string verbatim.
class ToneOption {
  final String id;
  final String label;
  final String desc;
  const ToneOption(this.id, this.label, this.desc);
}

/// Canonical tone list (DOMAIN VALUES). Default id == 'brief'.
const List<ToneOption> kTones = [
  ToneOption('warm', 'Warm', 'Reassuring, conversational'),
  ToneOption('balanced', 'Balanced', 'Direct but kind'),
  ToneOption('brief', 'Brief', '2–4 sentences, no fluff'),
];
const String kDefaultTone = 'brief';

/// All literature category ids (order = display order).
/// Synced with the directories in the server's documents/ folder:
///   conference_approved, books_about_aa, other_anonymous, related_nonfiction
const List<String> kAllCategories = [
  'other_anonymous',
  'conference_approved',
  'books_about_aa',
  'related_nonfiction',
];

/// Human labels for category ids.
const Map<String, String> kCategoryLabels = {
  'other_anonymous': 'Other Anonymous Fellowships',
  'conference_approved': 'Conference-Approved Literature',
  'books_about_aa': 'Books About A.A.',
  'related_nonfiction': 'Related Nonfiction',
};

const String kDefaultBaseUrl = 'https://sobrietycopilot.com';

/// Generates a stable-ish, uuid-like identifier for this install.
String _generateUserId() {
  final rng = Random();
  String hex(int bytes) {
    final sb = StringBuffer();
    for (var i = 0; i < bytes; i++) {
      sb.write(rng.nextInt(256).toRadixString(16).padLeft(2, '0'));
    }
    return sb.toString();
  }

  // 8-4-4-4-12 layout (not RFC-strict, but stable and unique enough).
  return '${hex(4)}-${hex(2)}-${hex(2)}-${hex(2)}-${hex(6)}';
}

String _normalizeBaseUrl(String value) {
  var v = value.trim();
  while (v.endsWith('/')) {
    v = v.substring(0, v.length - 1);
  }
  return v.isEmpty ? kDefaultBaseUrl : v;
}

/// Immutable app settings, persisted via SharedPreferences.
class AppConfig {
  final String baseUrl; // no trailing slash; default kDefaultBaseUrl
  final String tone; // one of kTones[].id
  final Set<String> enabledCategories; // subset of kAllCategories; default = all
  final bool showThinking; // default false
  final bool ttsEnabled; // default false
  // Opt-in "continue your study" cards derived on-device from local
  // conversation history. Never sent anywhere.
  final bool studySuggestions; // default false
  // Private Mode: answer with the on-device model instead of the server.
  // Only takes effect once the local model is downloaded and ready.
  final bool privateMode; // default false
  final String voiceId; // kSystemVoiceId or a NeuralVoice id
  final String userId; // stable per-install id (uuid-ish), never empty

  const AppConfig({
    required this.baseUrl,
    required this.tone,
    required this.enabledCategories,
    required this.showThinking,
    required this.ttsEnabled,
    this.studySuggestions = false,
    this.privateMode = false,
    required this.voiceId,
    required this.userId,
  });

  /// Defaults with all categories enabled and a freshly-generated userId.
  factory AppConfig.defaults({String? userId}) {
    final id = (userId != null && userId.isNotEmpty) ? userId : _generateUserId();
    return AppConfig(
      baseUrl: kDefaultBaseUrl,
      tone: kDefaultTone,
      enabledCategories: kAllCategories.toSet(),
      showThinking: false,
      ttsEnabled: false,
      studySuggestions: false,
      privateMode: false,
      voiceId: kSystemVoiceId,
      userId: id,
    );
  }

  AppConfig copyWith({
    String? baseUrl,
    String? tone,
    Set<String>? enabledCategories,
    bool? showThinking,
    bool? ttsEnabled,
    bool? studySuggestions,
    bool? privateMode,
    String? voiceId,
    String? userId,
  }) {
    return AppConfig(
      baseUrl: baseUrl ?? this.baseUrl,
      tone: tone ?? this.tone,
      enabledCategories: enabledCategories ?? this.enabledCategories,
      showThinking: showThinking ?? this.showThinking,
      ttsEnabled: ttsEnabled ?? this.ttsEnabled,
      studySuggestions: studySuggestions ?? this.studySuggestions,
      privateMode: privateMode ?? this.privateMode,
      voiceId: voiceId ?? this.voiceId,
      userId: userId ?? this.userId,
    );
  }

  factory AppConfig.fromJson(Map<String, dynamic> json) {
    final rawCats = json['enabledCategories'];
    Set<String> cats;
    if (rawCats is List) {
      cats = rawCats
          .map((e) => e.toString())
          .where(kAllCategories.contains)
          .toSet();
      if (cats.isEmpty) {
        // An empty stored set is ambiguous; only fall back to "all" when the
        // key was entirely missing. Here the list was explicitly empty, so we
        // keep it empty to honor the user's choice.
        cats = <String>{};
      }
    } else {
      cats = kAllCategories.toSet();
    }

    final rawTone = (json['tone'] as String?) ?? kDefaultTone;
    final tone =
        kTones.any((t) => t.id == rawTone) ? rawTone : kDefaultTone;

    final rawId = (json['userId'] as String?) ?? '';
    final userId = rawId.isNotEmpty ? rawId : _generateUserId();

    return AppConfig(
      baseUrl: _normalizeBaseUrl(
        (json['baseUrl'] as String?) ?? kDefaultBaseUrl,
      ),
      tone: tone,
      enabledCategories: cats,
      showThinking: json['showThinking'] as bool? ?? false,
      ttsEnabled: json['ttsEnabled'] as bool? ?? false,
      studySuggestions: json['studySuggestions'] as bool? ?? false,
      privateMode: json['privateMode'] as bool? ?? false,
      voiceId: (json['voiceId'] as String?) ?? kSystemVoiceId,
      userId: userId,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'baseUrl': baseUrl,
      'tone': tone,
      'enabledCategories': enabledCategories.toList()..sort(),
      'showThinking': showThinking,
      'ttsEnabled': ttsEnabled,
      'studySuggestions': studySuggestions,
      'privateMode': privateMode,
      'voiceId': voiceId,
      'userId': userId,
    };
  }

  /// For /api/chat: returns null when ALL categories are enabled
  /// (mirrors web "default = all = null"), else the sorted enabled list.
  List<String>? get categoriesForRequest {
    if (enabledCategories.length == kAllCategories.length &&
        kAllCategories.every(enabledCategories.contains)) {
      return null;
    }
    final list = enabledCategories.where(kAllCategories.contains).toList()
      ..sort();
    return list;
  }

  /// SharedPreferences key under which the whole config JSON is stored.
  static const String prefsKey = 'app_config_v1';
}

/// Riverpod notifier owning the persisted [AppConfig].
class AppConfigNotifier extends Notifier<AppConfig> {
  SharedPreferences get _prefs => ref.read(sharedPreferencesProvider);

  @override
  AppConfig build() {
    final raw = _prefs.getString(AppConfig.prefsKey);
    if (raw == null || raw.isEmpty) {
      final cfg = AppConfig.defaults();
      // Persist the freshly generated userId so it is stable across launches.
      _prefs.setString(AppConfig.prefsKey, jsonEncode(cfg.toJson()));
      return cfg;
    }
    try {
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      return AppConfig.fromJson(decoded);
    } catch (_) {
      final cfg = AppConfig.defaults();
      _prefs.setString(AppConfig.prefsKey, jsonEncode(cfg.toJson()));
      return cfg;
    }
  }

  Future<void> setBaseUrl(String value) async {
    state = state.copyWith(baseUrl: _normalizeBaseUrl(value));
    await _persist();
  }

  Future<void> setTone(String toneId) async {
    if (!kTones.any((t) => t.id == toneId)) return;
    state = state.copyWith(tone: toneId);
    await _persist();
  }

  Future<void> toggleCategory(String categoryId) async {
    if (!kAllCategories.contains(categoryId)) return;
    final next = state.enabledCategories.toSet();
    if (next.contains(categoryId)) {
      next.remove(categoryId);
    } else {
      next.add(categoryId);
    }
    state = state.copyWith(enabledCategories: next);
    await _persist();
  }

  Future<void> setCategoryEnabled(String categoryId, bool enabled) async {
    if (!kAllCategories.contains(categoryId)) return;
    final next = state.enabledCategories.toSet();
    if (enabled) {
      next.add(categoryId);
    } else {
      next.remove(categoryId);
    }
    state = state.copyWith(enabledCategories: next);
    await _persist();
  }

  Future<void> setAllCategories(bool enabled) async {
    state = state.copyWith(
      enabledCategories: enabled ? kAllCategories.toSet() : <String>{},
    );
    await _persist();
  }

  Future<void> setShowThinking(bool value) async {
    state = state.copyWith(showThinking: value);
    await _persist();
  }

  Future<void> setTtsEnabled(bool value) async {
    state = state.copyWith(ttsEnabled: value);
    await _persist();
  }

  Future<void> setStudySuggestions(bool value) async {
    state = state.copyWith(studySuggestions: value);
    await _persist();
  }

  Future<void> setPrivateMode(bool value) async {
    state = state.copyWith(privateMode: value);
    await _persist();
  }

  Future<void> setVoiceId(String value) async {
    state = state.copyWith(voiceId: value);
    await _persist();
  }

  Future<void> _persist() async {
    await _prefs.setString(
      AppConfig.prefsKey,
      jsonEncode(state.toJson()),
    );
  }
}
