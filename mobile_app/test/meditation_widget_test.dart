// Widget tests for the FR9 meditation sheet: library list, crisis note, and
// the player view renders with screen-reader text fallback.
//
// NOTE: The player auto-starts and drives a perpetual repeating animation, so
// tester.pumpAndSettle() would never settle. All pumps are bounded.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/meditation/meditation_sheet.dart';
import 'package:sobriety_copilot_mobile/features/meditation/player.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

class _FakeMedTts implements MedTts {
  @override
  Future<void> speak(String text) async {}

  @override
  Future<void> stop() async {}
}

Future<ProviderContainer> _container() async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      medTtsProvider.overrideWithValue(_FakeMedTts()),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: child, backgroundColor: Colors.transparent));

/// Bounded pump helper that advances frames just enough to build the sheet +
/// run the post-frame auto-start, without settling the infinite animation.
Future<void> _pumpSheet(WidgetTester tester, Widget widget) async {
  await tester.pumpWidget(widget);
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('library lists the curated sessions with surf the urge first',
      (tester) async {
    final container = await _container();
    await _pumpSheet(
      tester,
      UncontrolledProviderScope(
        container: container,
        child: _wrap(const MeditationSheet()),
      ),
    );

    expect(find.text('Meditation'), findsOneWidget);
    expect(find.text('Surf the Urge'), findsOneWidget);
    expect(find.text('4-7-8 Breathing'), findsOneWidget);
    expect(find.text('Box Breathing'), findsOneWidget);
    expect(find.text('Mini Body Scan'), findsOneWidget);
    // Surf the urge carries the crisis note (non-substitute line).
    expect(find.text(kCrisisNoteText), findsOneWidget);
  });

  testWidgets('tapping a session opens the player with a semantics fallback',
      (tester) async {
    final container = await _container();
    await _pumpSheet(
      tester,
      UncontrolledProviderScope(
        container: container,
        child: _wrap(const MeditationSheet()),
      ),
    );

    await tester.tap(find.text('4-7-8 Breathing'));
    await tester.pump(); // rebuild into player view
    await tester.pump(const Duration(milliseconds: 50)); // run post-frame start

    // Player view: step label + countdown text visible; breathing semantics.
    expect(find.text('Inhale'), findsWidgets);
    expect(find.byType(SwitchListTile), findsOneWidget);
    expect(
      find.bySemanticsLabel(RegExp(r'Inhale, \d+ seconds')),
      findsOneWidget,
    );

    // Stop the session so the auto-start Timer.periodic is cancelled before
    // the test ends (otherwise the framework asserts !timersPending).
    await container.read(meditationPlayerProvider.notifier).stop();
  });

  testWidgets('closing the player stops the session (returns to library)',
      (tester) async {
    final container = await _container();
    await _pumpSheet(
      tester,
      UncontrolledProviderScope(
        container: container,
        child: _wrap(const MeditationSheet()),
      ),
    );

    await tester.tap(find.text('Box Breathing'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(container.read(meditationPlayerProvider).session, isNotNull);

    // Tap the close (X) button — the player's stop + pop.
    await tester.tap(find.byIcon(Icons.close));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(container.read(meditationPlayerProvider).session, isNull);
  });
}
