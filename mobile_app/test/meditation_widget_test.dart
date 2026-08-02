// Widget tests for the FR9 meditation sheet: library list, crisis note, and
// the player view renders with screen-reader text fallback.
//
// NOTE: The session tile starts the session on tap and the player drives a
// perpetual repeating animation, so tester.pumpAndSettle() would never settle.
// All pumps are bounded.

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

/// Bounded pump helper that advances frames just enough to build the sheet,
/// without settling the infinite breathing animation.
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
    await tester.pump(); // rebuild into player view (tile starts the session)
    await tester.pump(const Duration(milliseconds: 50));

    // Player view: step label + countdown text visible; breathing semantics.
    // The live region carries ONLY the step label — never the countdown,
    // which would flood screen readers with an announcement every second.
    expect(find.text('Inhale'), findsWidgets);
    expect(find.byType(SwitchListTile), findsOneWidget);
    expect(find.bySemanticsLabel('Inhale'), findsOneWidget);
    expect(
      find.bySemanticsLabel(RegExp(r'Inhale, \d+ seconds')),
      findsNothing,
    );

    // Stop the session so the Timer.periodic is cancelled before the test
    // ends (otherwise the framework asserts !timersPending).
    await container.read(meditationPlayerProvider.notifier).stop();
  });

  testWidgets('dismissing the sheet fully stops a running session',
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
    expect(container.read(meditationPlayerProvider).running, isTrue);

    // Simulate drag/barrier dismissal: the sheet leaves the tree without the
    // close button being tapped. The player must not keep running headless.
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: _wrap(const SizedBox()),
      ),
    );
    await tester.pump(const Duration(milliseconds: 50));

    final s = container.read(meditationPlayerProvider);
    expect(s.session, isNull);
    expect(s.running, isFalse);
  });

  testWidgets('completed session shows a terminal Done panel, no resume',
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
    await tester.pump();
    final p = container.read(meditationPlayerProvider.notifier);
    final total =
        container.read(meditationPlayerProvider).session!.totalSeconds;
    for (var i = 0; i < total; i++) {
      p.tick(); // drive to completion without real time
    }
    await tester.pump();

    expect(find.text('Done'), findsOneWidget);
    expect(find.byIcon(Icons.play_circle_outline), findsNothing);
    expect(find.bySemanticsLabel('Session complete'), findsOneWidget);
    expect(p.completedCount, 1);

    // Done returns to the library; the completion count is untouched.
    await tester.tap(find.text('Done'));
    await tester.pump(const Duration(milliseconds: 50));
    expect(container.read(meditationPlayerProvider).session, isNull);
    expect(p.completedCount, 1);
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
