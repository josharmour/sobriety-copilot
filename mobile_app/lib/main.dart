import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/platform_init.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  initPlatform();
  final prefs = await SharedPreferences.getInstance();
  runApp(
    ProviderScope(
      overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
      child: const SobrietyCopilotApp(),
    ),
  );
}

class SobrietyCopilotApp extends StatelessWidget {
  const SobrietyCopilotApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sobriety Copilot',
      debugShowCheckedModeBanner: false,
      theme: buildLightTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: ThemeMode.dark,
      home: const ChatScreen(),
    );
  }
}
