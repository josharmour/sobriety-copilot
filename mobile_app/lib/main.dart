import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'package:flutter_gemma/flutter_gemma.dart';
import 'package:flutter_gemma_litertlm/flutter_gemma_litertlm.dart';
import 'package:flutter_gemma_embeddings/flutter_gemma_embeddings.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/library/offline_reader.dart';
import 'package:sobriety_copilot_mobile/platform_init.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_screen.dart';
import 'package:sobriety_copilot_mobile/features/daily/daily_readings.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/model_manager.dart';

/// Parses a deep-link URI and navigates to the appropriate screen.
///
/// Supported URIs:
///   sobriety-copilot://offline-reader?docId={id}&title={title}[&highlights={id1},{id2}]
void _handleDeepLink(BuildContext context, Uri uri) {
  if (uri.host == 'offline-reader') {
    final docId = uri.queryParameters['docId'];
    final title = uri.queryParameters['title'] ?? 'Literature';
    final highlightsParam = uri.queryParameters['highlights'];
    if (docId != null && docId.isNotEmpty && context.mounted) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => OfflineReaderScreen(
            docId: docId,
            title: Uri.decodeComponent(title),
            highlightBlockIds:
                highlightsParam != null && highlightsParam.isNotEmpty
                    ? highlightsParam.split(',').map((s) => s.trim()).toList()
                    : null,
          ),
        ),
      );
    }
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  initPlatform();
  if (privateModeSupported) {
    // On-device LLM plumbing (Private Mode). Cheap when no model is set up.
    await FlutterGemma.initialize(
      inferenceEngines: const [LiteRtLmEngine()],
      embeddingBackends: const [LiteRtEmbeddingBackend()],
    );
  }
  final prefs = await SharedPreferences.getInstance();
  runApp(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      child: const SobrietyCopilotApp(),
    ),
  );
}

class SobrietyCopilotApp extends ConsumerStatefulWidget {
  const SobrietyCopilotApp({super.key});

  @override
  ConsumerState<SobrietyCopilotApp> createState() => _SobrietyCopilotAppState();
}

class _SobrietyCopilotAppState extends ConsumerState<SobrietyCopilotApp> {
  late final AppLinks _appLinks;

  @override
  void initState() {
    super.initState();
    _appLinks = AppLinks();
    _initDeepLinks();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(sobrietyProvider);
      ref.read(dailyReadingsProvider);
    });
  }

  Future<void> _initDeepLinks() async {
    // Handle link that launched the app (cold start)
    try {
      final initialUri = await _appLinks.getInitialLink();
      if (initialUri != null && mounted) {
        _handleDeepLink(context, initialUri);
      }
    } catch (_) {
      // No initial link — fine.
    }

    // Handle links while the app is running (warm start)
    _appLinks.uriLinkStream.listen((Uri uri) {
      if (mounted) {
        _handleDeepLink(context, uri);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final config = ref.watch(appConfigProvider);
    return MaterialApp(
      title: 'Sobriety Copilot',
      debugShowCheckedModeBanner: false,
      theme: buildLightTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: config.themeMode,
      home: const ChatScreen(),
    );
  }
}
