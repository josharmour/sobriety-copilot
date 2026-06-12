import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/models/meeting_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository.dart';
import 'package:sobriety_copilot_mobile/data/repositories/suggest_repository.dart';
import 'package:sobriety_copilot_mobile/data/repositories/meeting_repository.dart';
import 'package:sobriety_copilot_mobile/data/repositories/server_repository.dart';
import 'package:sobriety_copilot_mobile/data/repositories/library_repository.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_notifier.dart';
import 'package:sobriety_copilot_mobile/features/chat/conversations.dart';
import 'package:sobriety_copilot_mobile/features/chat/saved_passages.dart';
import 'package:sobriety_copilot_mobile/features/tts/tts_service.dart';
import 'package:sobriety_copilot_mobile/features/tts/voice_manager.dart';

/// Resolved [SharedPreferences] instance.
///
/// Overridden in `main()` via
/// `sharedPreferencesProvider.overrideWithValue(prefs)`. The unimplemented
/// default guarantees a loud failure if the override is ever forgotten.
final sharedPreferencesProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError(
    'sharedPreferencesProvider must be overridden in main()',
  ),
);

/// Shared [http.Client] for all repositories. Closed when the container is
/// disposed.
final httpClientProvider = Provider<http.Client>((ref) {
  final c = http.Client();
  ref.onDispose(c.close);
  return c;
});

/// App-wide settings (base URL, tone, categories, flags). Backed by
/// [SharedPreferences].
final appConfigProvider =
    NotifierProvider<AppConfigNotifier, AppConfig>(AppConfigNotifier.new);

/// Live base-URL closure read from [appConfigProvider]. Passing this closure
/// (rather than a snapshot string) into the repositories means changing the
/// base URL in settings takes effect immediately without rebuilding them.
String _baseUrl(Ref ref) => ref.read(appConfigProvider).baseUrl;

/// Streaming chat repository (`POST /api/chat`).
final chatRepositoryProvider = Provider<ChatRepository>((ref) {
  return HttpChatRepository(
    client: ref.watch(httpClientProvider),
    baseUrl: () => _baseUrl(ref),
  );
});

/// Autocomplete repository (`GET /api/suggest`).
final suggestRepositoryProvider = Provider<SuggestRepository>((ref) {
  return SuggestRepository(
    client: ref.watch(httpClientProvider),
    baseUrl: () => _baseUrl(ref),
  );
});

/// Meetings / geocode repository (`GET /api/geocode`, `GET /api/meetings`).
final meetingRepositoryProvider = Provider<MeetingRepository>((ref) {
  return MeetingRepository(
    client: ref.watch(httpClientProvider),
    baseUrl: () => _baseUrl(ref),
  );
});

/// Server health / connectivity repository (`GET /api/health`).
final serverRepositoryProvider = Provider<ServerRepository>((ref) {
  return ServerRepository(
    client: ref.watch(httpClientProvider),
    baseUrl: () => _baseUrl(ref),
  );
});

/// Offline library repository (check packs, download, search).
final libraryRepositoryProvider = Provider<LibraryRepository>((ref) {
  return LibraryRepository(
    client: ref.watch(httpClientProvider),
    prefs: ref.watch(sharedPreferencesProvider),
    baseUrl: () => _baseUrl(ref),
  );
});

/// Live chat screen state (messages, sending, streaming).
final chatNotifierProvider =
    NotifierProvider<ChatNotifier, ChatState>(ChatNotifier.new);

/// Persisted conversation history.
final conversationsProvider =
    NotifierProvider<ConversationsNotifier, List<Conversation>>(
  ConversationsNotifier.new,
);

/// Persisted bookmarked source passages.
final savedPassagesProvider =
    NotifierProvider<SavedPassagesNotifier, List<Source>>(
  SavedPassagesNotifier.new,
);

/// Live autocomplete results for the current input, keyed by the query string.
///
/// Returns `[]` for queries shorter than 2 characters (mirrors the server's
/// `len(q) < 2` short-circuit) and on any error.
final suggestionsProvider =
    FutureProvider.autoDispose.family<List<Suggestion>, String>((ref, q) async {
  final query = q.trim();
  if (query.length < 2) return const <Suggestion>[];
  final categories = ref.read(appConfigProvider).categoriesForRequest;
  try {
    return await ref
        .watch(suggestRepositoryProvider)
        .suggest(query, categories: categories);
  } catch (_) {
    return const <Suggestion>[];
  }
});

/// Server health status. AutoDispose so it re-queries when re-watched; can be
/// refreshed via `ref.invalidate(healthProvider)`.
final healthProvider = FutureProvider.autoDispose<HealthStatus>((ref) async {
  return ref.watch(serverRepositoryProvider).health();
});

/// Downloadable neural voice install state (download / extract / delete).
final voiceManagerProvider =
    NotifierProvider<VoiceManagerNotifier, Map<String, VoiceStatus>>(
  VoiceManagerNotifier.new,
);

/// App-wide read-aloud service (system or neural voice per [AppConfig.voiceId]).
final appTtsProvider = Provider<AppTts>((ref) {
  final tts = AppTts(ref);
  ref.onDispose(tts.dispose);
  return tts;
});
