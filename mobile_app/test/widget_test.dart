// Basic smoke test for the Sobriety Copilot app.
//
// Builds the root app widget inside a ProviderScope with a fake
// SharedPreferences, and verifies it renders without throwing.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/main.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

void main() {
  testWidgets('App builds and renders the chat screen', (
    WidgetTester tester,
  ) async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final prefs = await SharedPreferences.getInstance();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
        child: const SobrietyCopilotApp(),
      ),
    );
    await tester.pump();

    // The root MaterialApp should be present.
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
