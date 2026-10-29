import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_screen.dart';
import 'package:sobriety_copilot_mobile/features/daily/mood_log.dart';
import 'package:sobriety_copilot_mobile/features/daily/inventory.dart';
import 'package:sobriety_copilot_mobile/features/home/day_home.dart';
import 'package:sobriety_copilot_mobile/features/tts/tts_service.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/features/chat/conversations.dart';
import 'resume_chip_test.dart' show FakeChatRepository;

class _SilentTts implements AppTts {
  @override
  void Function()? onDone;
  @override
  Future<void> stop() async {}
  @override
  Future<void> speak(String text) async {}
  @override
  void dispose() {}
}

Future<ProviderContainer> harness(
  WidgetTester tester, {
  bool enabled = true,
  double scale = 1,
  Map<String, Object> initialPreferences = const {},
}) async {
  SharedPreferences.setMockInitialValues(initialPreferences);
  final prefs = await SharedPreferences.getInstance();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      chatRepositoryProvider.overrideWithValue(FakeChatRepository()),
      appTtsProvider.overrideWithValue(_SilentTts()),
    ],
  );
  addTearDown(container.dispose);
  addTearDown(() => tester.pumpWidget(const SizedBox()));
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        theme: buildLightTheme(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(scale)),
          child: child!,
        ),
        home: ChatScreen(dayHomeEnabled: enabled),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return container;
}

void main() {
  test('the approved home is enabled in ordinary production builds', () {
    expect(const ChatScreen().dayHomeEnabled, isTrue);
  });

  testWidgets('existing saved conversations open visibly from the home menu', (
    tester,
  ) async {
    final conversation = Conversation.create().copyWith(
      title: 'Previously saved conversation',
      messages: [ChatMessage.user('Existing local history')],
    );
    final saved = jsonEncode([conversation.toJson()]);
    final container = await harness(
      tester,
      initialPreferences: {ConversationsNotifier.prefsKey: saved},
    );
    await tester.tap(find.byTooltip('Conversations'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Previously saved conversation'));
    await tester.pumpAndSettle();
    expect(find.text('Existing local history'), findsOneWidget);
    expect(
      tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
      1,
    );
    expect(
      container
          .read(sharedPreferencesProvider)
          .getString(ConversationsNotifier.prefsKey),
      saved,
    );
  });

  testWidgets('home controls meet mobile accessibility guidelines', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    await harness(tester);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(iOSTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    handle.dispose();
  });
  testWidgets('home navigation preserves an unsent chat draft', (tester) async {
    await harness(tester);
    expect(find.text('A little space for today.'), findsOneWidget);
    await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'A draft to keep');
    await tester.tap(find.widgetWithText(NavigationDestination, 'Library'));
    await tester.pumpAndSettle();
    expect(find.text('Explore connected ideas'), findsOneWidget);
    await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
    await tester.pumpAndSettle();
    expect(find.text('A draft to keep'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('check-in completion comes from local saved state', (
    tester,
  ) async {
    final container = await harness(tester);
    expect(find.text('Check in'), findsOneWidget);
    await container
        .read(moodProvider.notifier)
        .upsert(
          MoodEntry(
            dateIso: dateIsoOf(DateTime.now()),
            mood: 3,
            label: 'Okay',
            journal: '',
          ),
        );
    await tester.pumpAndSettle();
    expect(find.text('Revisit check-in'), findsOneWidget);
    expect(find.text('You made space today.'), findsOneWidget);
  });

  testWidgets('all home destinations fit narrow screens at 200 percent text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await harness(tester, scale: 2);
    for (final label in ['Today', 'Library', 'You']) {
      await tester.tap(find.widgetWithText(NavigationDestination, label));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: label);
    }
  });

  testWidgets('default screen keeps the existing chat when prototype is off', (
    tester,
  ) async {
    await harness(tester, enabled: false);
    expect(find.byType(DayHome), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.text('A little room to think.'), findsOneWidget);
  });
}
