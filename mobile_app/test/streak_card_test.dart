// Widget tests for the FR5 StreakCard display states — especially the ones
// that carry the tone requirements: a lapsed run must never be advertised as
// live (no N-to-1 collapse in front of the user), and post-relapse copy must
// welcome rather than mourn.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/milestones/streak_card.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

Future<ProviderContainer> _container() async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],
  );
  addTearDown(container.dispose);
  return container;
}

Future<void> _pump(WidgetTester tester, ProviderContainer c) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: c,
      child: const MaterialApp(home: Scaffold(body: StreakCard())),
    ),
  );
  await tester.pump();
}

DateTime _daysAgo(int n) {
  final now = DateTime.now();
  return DateTime(now.year, now.month, now.day - n);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('never checked in: invites without pressure', (tester) async {
    final c = await _container();
    await _pump(tester, c);
    expect(find.text('Show up for yourself today.'), findsOneWidget);
    expect(find.text('Check in for today'), findsOneWidget);
    expect(find.textContaining('Best:'), findsNothing);
  });

  testWidgets('checked in today: shows the run and hides the button',
      (tester) async {
    final c = await _container();
    final n = c.read(streakProvider.notifier);
    await n.recordCheckIn(now: _daysAgo(1));
    await n.recordCheckIn(now: _daysAgo(0));
    await _pump(tester, c);

    expect(find.text('You showed up for yourself 2 days in a row.'),
        findsOneWidget);
    expect(find.text('Checked in'), findsOneWidget);
    expect(find.text('Check in for today'), findsNothing);
  });

  testWidgets('lapsed run is never advertised as live — no N-to-1 collapse',
      (tester) async {
    final c = await _container();
    final n = c.read(streakProvider.notifier);
    // A real 5-day run that ended three days ago.
    for (var i = 7; i >= 3; i--) {
      await n.recordCheckIn(now: _daysAgo(i));
    }
    expect(c.read(streakProvider).current, 5); // stored run is intact
    await _pump(tester, c);

    // The card must NOT claim the 5-day run is still going.
    expect(find.textContaining('5 days in a row'), findsNothing);
    expect(find.text("A new streak starts whenever you're ready."),
        findsOneWidget);
    expect(find.textContaining('Best: 5 days'), findsOneWidget);

    // Checking in shows a welcome, never the collapse from 5.
    await tester.tap(find.text('Check in for today'));
    await tester.pump();
    expect(find.text('Welcome back — day 1 of a new streak.'), findsOneWidget);
    expect(find.textContaining('5 days in a row'), findsNothing);
    expect(find.textContaining('Best: 5 days'), findsOneWidget);
  });

  testWidgets('after a relapse reset the card welcomes and offers check-in',
      (tester) async {
    final c = await _container();
    final n = c.read(streakProvider.notifier);
    await n.recordCheckIn(now: _daysAgo(1));
    await n.recordCheckIn(now: _daysAgo(0));
    await n.reset(); // what logRelapse does

    await _pump(tester, c);
    expect(find.text("A new streak starts whenever you're ready."),
        findsOneWidget);
    expect(find.textContaining('Best: 2 days'), findsOneWidget);
    // Showing up again today is possible immediately.
    expect(find.text('Check in for today'), findsOneWidget);
    await tester.tap(find.text('Check in for today'));
    await tester.pump();
    expect(find.text('Welcome back — day 1 of a new streak.'), findsOneWidget);
  });

  testWidgets('card carries no recovery wording (discreet-safe)',
      (tester) async {
    final c = await _container();
    final n = c.read(streakProvider.notifier);
    await n.recordCheckIn(now: _daysAgo(0));
    await _pump(tester, c);

    final texts = tester
        .widgetList<Text>(find.byType(Text))
        .map((t) => (t.data ?? '').toLowerCase())
        .join(' ');
    for (final banned in [
      'sober',
      'sobriety',
      'recovery',
      'relapse',
      'clean',
      'addict',
    ]) {
      expect(texts.contains(banned), isFalse,
          reason: 'streak card must not contain "$banned"');
    }
  });

  testWidgets('week dots expose one summary label, not seven', (tester) async {
    final c = await _container();
    final n = c.read(streakProvider.notifier);
    await n.recordCheckIn(now: _daysAgo(1));
    await n.recordCheckIn(now: _daysAgo(0));
    await _pump(tester, c);
    expect(find.bySemanticsLabel('Last 7 days: 2 check-ins'), findsOneWidget);
  });
}
