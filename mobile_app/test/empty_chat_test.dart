import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sobriety_copilot_mobile/features/chat/empty_chat_landing.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'day_home_test.dart' as home;
import 'resume_chip_test.dart' show FakeChatRepository;

void main() {
  Future<void> landing(
    WidgetTester tester,
    TextEditingController controller, {
    bool active = true,
    bool reduced = false,
    bool dark = false,
    double scale = 1,
    ValueChanged<String>? pick,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: dark ? buildDarkTheme() : buildLightTheme(),
        home: MediaQuery(
          data: MediaQueryData(
            disableAnimations: reduced,
            textScaler: TextScaler.linear(scale),
          ),
          child: Scaffold(
            body: EmptyChatLanding(
              controller: controller,
              active: active,
              prompts: const [
                'A starting thought',
                'Another thought',
                'One more thought',
              ],
              onPick: pick ?? (_) {},
              composer: TextField(controller: controller),
            ),
          ),
        ),
      ),
    );
  }

  testWidgets(
    'idle reveal stays still; typing hides ideas without moving composer or caret',
    (tester) async {
      final controller = TextEditingController();
      await landing(tester, controller);
      await tester.pump(const Duration(milliseconds: 700));
      final before = tester.getRect(find.byType(TextField));
      expect(
        tester
            .widget<OutlinedButton>(
              find.byKey(const ValueKey('thought-bubble-0')),
            )
            .onPressed,
        isNull,
      );
      await tester.pump(const Duration(seconds: 2));
      await tester.pump(const Duration(milliseconds: 1100));
      expect(
        tester
            .widget<OutlinedButton>(
              find.byKey(const ValueKey('thought-bubble-0')),
            )
            .onPressed,
        isNotNull,
      );
      expect(tester.getRect(find.byType(TextField)), before);
      await tester.enterText(find.byType(TextField), 'My draft');
      controller.selection = const TextSelection.collapsed(offset: 3);
      await tester.pump();
      expect(
        tester
            .widget<OutlinedButton>(
              find.byKey(const ValueKey('thought-bubble-0')),
            )
            .onPressed,
        isNull,
      );
      expect(controller.selection.baseOffset, 3);
      expect(tester.getRect(find.byType(TextField)), before);
      await tester.pump(const Duration(seconds: 10));
      expect(
        tester
            .widget<OutlinedButton>(
              find.byKey(const ValueKey('thought-bubble-0')),
            )
            .onPressed,
        isNull,
      );
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets('inactive tabs cancel idle and dispose never leaves a callback', (
    tester,
  ) async {
    final controller = TextEditingController();
    await landing(tester, controller);
    await tester.pump(const Duration(seconds: 1));
    await landing(tester, controller, active: false);
    await tester.pump(const Duration(seconds: 5));
    expect(
      tester
          .widget<OutlinedButton>(
            find.byKey(const ValueKey('thought-bubble-0')),
          )
          .onPressed,
      isNull,
    );
    await landing(tester, controller);
    await tester.pump(const Duration(seconds: 2));
    expect(
      tester
          .widget<OutlinedButton>(
            find.byKey(const ValueKey('thought-bubble-0')),
          )
          .onPressed,
      isNull,
    );
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 5));
    expect(tester.takeException(), isNull);
    controller.dispose();
  });

  testWidgets(
    'reduced motion reveals without movement and removes hidden ideas from semantics',
    (tester) async {
      final semantics = tester.ensureSemantics();
      final controller = TextEditingController();
      await landing(tester, controller, reduced: true);
      expect(find.bySemanticsLabel('A starting thought'), findsNothing);
      await tester.pump(const Duration(milliseconds: 2400));
      expect(find.bySemanticsLabel('A starting thought'), findsOneWidget);
      final bubble = find.byKey(const ValueKey('thought-bubble-0'));
      expect(
        tester
            .widget<Opacity>(
              find.ancestor(of: bubble, matching: find.byType(Opacity)).first,
            )
            .opacity,
        1,
      );
      final position = tester.getRect(bubble);
      await tester.pump(const Duration(milliseconds: 100));
      expect(tester.getRect(bubble), position);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
      semantics.dispose();
    },
  );

  testWidgets(
    'suggestion fills a draft; explicit send enters unchanged conversation and new chat resets',
    (tester) async {
      final container = await home.harness(tester);
      addTearDown(() => tester.pumpWidget(const SizedBox()));
      final repo = container.read(chatRepositoryProvider) as FakeChatRepository;
      await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(milliseconds: 2400));
      await tester.pumpAndSettle();
      final bubble = find.byKey(const ValueKey('thought-bubble-0'));
      await tester.ensureVisible(bubble);
      await tester.tap(bubble);
      await tester.pump();
      expect(repo.sends, 0);
      final field = tester.widget<TextField>(find.byType(TextField));
      expect(
        field.controller!.text,
        'Share a daily reflection about acceptance.',
      );
      expect(field.focusNode!.hasFocus, isTrue);
      await tester.ensureVisible(find.byTooltip('Send'));
      await tester.tap(find.byTooltip('Send'));
      await tester.pumpAndSettle();
      expect(repo.sends, 1);
      expect(
        container.read(chatNotifierProvider).messages.first.text,
        'Share a daily reflection about acceptance.',
      );
      expect(find.byType(EmptyChatLanding), findsNothing);
      expect(find.text('Picking that back up.'), findsOneWidget);
      await tester.tap(find.byTooltip('New conversation'));
      await tester.pumpAndSettle();
      expect(find.byType(EmptyChatLanding), findsOneWidget);
      expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text,
        isEmpty,
      );
    },
  );

  testWidgets(
    'real composer remains reachable with keyboard space and large text',
    (tester) async {
      tester.view.physicalSize = const Size(390, 500);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await home.harness(tester, scale: 2);
      await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byType(TextField));
      await tester.enterText(
        find.byType(TextField),
        'A draft on a small screen',
      );
      await tester.pump();
      await tester.ensureVisible(find.byTooltip('Send'));
      expect(find.byTooltip('Send').hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'visible prompt and composer controls meet accessible tap targets',
    (tester) async {
      final semantics = tester.ensureSemantics();
      await home.harness(tester);
      await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(iOSTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      semantics.dispose();
    },
  );

  for (final dark in [false, true]) {
    testWidgets(
      'compact layout, keyboard height and 200 percent text in ${dark ? 'dark' : 'light'} theme',
      (tester) async {
        tester.view.physicalSize = const Size(320, 420);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final controller = TextEditingController();
        await landing(tester, controller, dark: dark, scale: 2);
        await tester.pump(const Duration(seconds: 3));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.ensureVisible(find.byType(TextField));
        await tester.enterText(
          find.byType(TextField),
          'A longer draft that wraps on a small screen.',
        );
        await tester.pump();
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        controller.dispose();
      },
    );
  }
}
