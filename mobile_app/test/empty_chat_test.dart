import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/services.dart';
import 'package:sobriety_copilot_mobile/data/starter_prompts.dart';
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
    List<String>? prompts,
    List<String> Function(int, Set<String>)? loader,
    bool screenReader = false,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: dark ? buildDarkTheme() : buildLightTheme(),
        home: MediaQuery(
          data: MediaQueryData(
            disableAnimations: reduced,
            accessibleNavigation: screenReader,
            size: tester.view.physicalSize / tester.view.devicePixelRatio,
            textScaler: TextScaler.linear(scale),
          ),
          child: Scaffold(
            body: EmptyChatLanding(
              controller: controller,
              active: active,
              loadPrompts: loader,
              prompts:
                  prompts ??
                  const [
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

  testWidgets('bubble sends exactly once immediately and new chat resets', (
    tester,
  ) async {
    final container = await home.harness(tester);
    addTearDown(() => tester.pumpWidget(const SizedBox()));
    final repo = container.read(chatRepositoryProvider) as FakeChatRepository;
    await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(milliseconds: 2400));
    await tester.pumpAndSettle();
    final bubble = find.byKey(const ValueKey('thought-bubble-0'));
    await tester.ensureVisible(bubble);
    final button = tester.widget<OutlinedButton>(bubble);
    final prompt = (button.child! as Text).data!;
    final queuedActivation = button.onPressed!;
    await tester.tap(bubble);
    queuedActivation();
    queuedActivation();
    await tester.pumpAndSettle();
    expect(repo.sends, 1);
    expect(container.read(chatNotifierProvider).messages.first.text, prompt);
    expect(find.byType(EmptyChatLanding), findsNothing);
    expect(find.text('Picking that back up.'), findsOneWidget);
    await tester.tap(find.byTooltip('New conversation'));
    await tester.pumpAndSettle();
    expect(find.byType(EmptyChatLanding), findsOneWidget);
    expect(
      tester.widget<TextField>(find.byType(TextField)).controller!.text,
      isEmpty,
    );
  });

  testWidgets(
    'keyboard activation submits once and normal errors keep the user query',
    (tester) async {
      final container = await home.harness(tester);
      final repo = container.read(chatRepositoryProvider) as FakeChatRepository;
      repo.failure = 'Preview connection failed';
      await tester.tap(find.widgetWithText(NavigationDestination, 'Chat'));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(milliseconds: 2400));
      await tester.pumpAndSettle();
      final bubble = find.byKey(const ValueKey('thought-bubble-0'));
      await tester.ensureVisible(bubble);
      final button = tester.widget<OutlinedButton>(bubble);
      final prompt = (button.child! as Text).data!;
      Focus.of(tester.element(find.text(prompt))).requestFocus();
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      button.onPressed!();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pump(const Duration(seconds: 20));
      expect(repo.sends, 1);
      expect(container.read(chatNotifierProvider).messages.first.text, prompt);
      expect(container.read(chatNotifierProvider).isSending, isFalse);
      expect(find.byType(EmptyChatLanding), findsNothing);
      expect(find.textContaining('Preview connection failed'), findsWidgets);
    },
  );

  for (final width in [390.0, 1280.0]) {
    testWidgets(
      'rotating corpus stays bounded and composer anchored at width $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final controller = TextEditingController();
        final pool = List.generate(80, (i) => 'Catalog question $i?');
        await landing(tester, controller, prompts: pool);
        await tester.pump(const Duration(seconds: 3));
        await tester.pumpAndSettle();
        final anchor = tester.getRect(find.byType(TextField));
        final observed = <String>{};
        for (var cycle = 0; cycle < 12; cycle++) {
          await tester.pump(const Duration(seconds: 7));
          await tester.pumpAndSettle();
          final buttons = tester.widgetList<OutlinedButton>(
            find.byType(OutlinedButton),
          );
          expect(buttons.length, width < 700 ? 3 : 5);
          observed.addAll(buttons.map((b) => (b.child! as Text).data!));
          expect(tester.getRect(find.byType(TextField)), anchor);
          expect(tester.takeException(), isNull);
        }
        expect(observed.length, greaterThan(10));
        await tester.enterText(find.byType(TextField), 'A draft');
        final before = tester
            .widgetList<OutlinedButton>(find.byType(OutlinedButton))
            .map((b) => (b.child! as Text).data)
            .toList();
        await tester.pump(const Duration(seconds: 60));
        expect(
          tester
              .widgetList<OutlinedButton>(find.byType(OutlinedButton))
              .map((b) => (b.child! as Text).data)
              .toList(),
          before,
        );
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
  }

  testWidgets(
    'narrowing the viewport during replacement cancels the outgoing slot safely',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = TextEditingController();
      final pool = List.generate(40, (i) => 'Question $i?');
      await landing(tester, controller, prompts: pool);
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 7));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 7));
      await tester.pump(const Duration(milliseconds: 100));
      tester.view.physicalSize = const Size(390, 844);
      await landing(tester, controller, prompts: pool);
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.byType(OutlinedButton), findsNWidgets(3));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets(
    'hover and keyboard focus protect the question from replacement',
    (tester) async {
      final controller = TextEditingController();
      await landing(
        tester,
        controller,
        prompts: List.generate(30, (i) => 'Question $i?'),
      );
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      final bubble = find.byKey(const ValueKey('thought-bubble-0'));
      final original =
          (tester.widget<OutlinedButton>(bubble).child! as Text).data!;
      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      await mouse.addPointer(location: tester.getCenter(bubble));
      await tester.pump();
      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(
        (tester.widget<OutlinedButton>(bubble).child! as Text).data,
        original,
      );
      Focus.of(tester.element(find.text(original))).requestFocus();
      await tester.pump();
      await mouse.moveTo(Offset.zero);
      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(
        (tester.widget<OutlinedButton>(bubble).child! as Text).data,
        original,
      );
      await mouse.removePointer();
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets(
    'screen reader mode offers manual ideas instead of timed replacements',
    (tester) async {
      final controller = TextEditingController();
      await landing(
        tester,
        controller,
        screenReader: true,
        prompts: List.generate(30, (i) => 'Question $i?'),
      );
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.byType(OutlinedButton), findsNWidgets(3));
      await tester.pump(const Duration(seconds: 60));
      expect(find.byType(OutlinedButton), findsNWidgets(3));
      await tester.tap(find.text('More ideas'));
      await tester.pumpAndSettle();
      expect(find.byType(OutlinedButton), findsNWidgets(5));
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets(
    'picker failure falls back without repeats or endless callbacks',
    (tester) async {
      final controller = TextEditingController();
      await landing(
        tester,
        controller,
        loader: (_, __) => throw StateError('unavailable'),
      );
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.byType(OutlinedButton), findsNWidgets(3));
      await tester.pump(const Duration(seconds: 10));
      await tester.pumpAndSettle();
      expect(find.byType(OutlinedButton), findsNWidgets(3));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  test(
    'bundled graph corpus preserves all topics and thousands of public questions',
    () {
      final catalog = kRecoveryTopicCatalog.fold<int>(
        0,
        (sum, topic) => sum + topic.prompts.length,
      );
      // Logged as release-review evidence, derived from the compiled catalog.
      debugPrint(
        'Graph corpus: ${kRecoveryTopicCatalog.length} topics, $catalog catalog prompts, ${kAllStarterPrompts.length} unique combined prompts',
      );
      expect(kRecoveryTopicCatalog.length, 92);
      expect(catalog, 1790);
      expect(kAllStarterPrompts.length, greaterThan(1700));
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
