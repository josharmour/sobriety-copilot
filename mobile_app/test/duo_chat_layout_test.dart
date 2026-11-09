import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'day_home_test.dart' as home;
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';

void main() {
  testWidgets(
    'real chat respects side status region while folding and typing',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(466, 678);
      tester.view.padding = const FakeViewPadding(right: 84);
      tester.view.viewPadding = const FakeViewPadding(right: 84);
      addTearDown(tester.view.reset);
      await home.harness(tester);
      await tester.enterText(find.byType(TextField).first, 'A private draft');
      await tester.pump();
      final draft =
          tester.widget<TextField>(find.byType(TextField).first).controller!;
      draft.selection = const TextSelection.collapsed(offset: 4);
      void check() {
        final appBar = tester.getRect(find.byType(AppBar));
        final input = tester.getRect(find.byType(TextField).first);
        final nav = tester.getRect(find.byType(NavigationBar));
        expect(input.left, greaterThanOrEqualTo(appBar.left));
        expect(input.right, lessThanOrEqualTo(appBar.right));
        expect(nav.left, appBar.left);
        expect(nav.right, appBar.right);
        expect(draft.text, 'A private draft');
        expect(draft.selection.baseOffset, 4);
        expect(tester.takeException(), isNull);
      }

      check();
      tester.view.physicalSize = const Size(951, 669);
      tester.view.padding = const FakeViewPadding(left: 84);
      tester.view.viewPadding = const FakeViewPadding(left: 84);
      await tester.pump();
      check();
      tester.view.physicalSize = const Size(466, 678);
      tester.view.padding = const FakeViewPadding(right: 84);
      tester.view.viewPadding = const FakeViewPadding(right: 84);
      tester.view.viewInsets = const FakeViewPadding(bottom: 260);
      await tester.pump();
      check();
    },
  );
  for (final scale in [1.0, 2.0]) {
    testWidgets(
      'selected citation stays open through fold at text scale $scale',
      (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = const Size(951, 669);
        tester.view.padding = const FakeViewPadding(right: 84);
        tester.view.viewPadding = const FakeViewPadding(right: 84);
        addTearDown(tester.view.reset);
        final container = await home.harness(tester, scale: scale);
        final sources = [
          Source(
            source: 'First.pdf',
            similarity: 0,
            url: '/first',
            excerpt: 'First test passage',
          ),
          Source(
            source: 'Second.pdf',
            similarity: 0,
            url: '/second',
            excerpt: List.filled(
              35,
              'Second test passage for reading.',
            ).join('\n'),
          ),
        ];
        container
            .read(chatNotifierProvider.notifier)
            .loadConversation(
              Conversation.create().copyWith(
                messages: [
                  ChatMessage.user('A sample question'),
                  ChatMessage.assistantPlaceholder().copyWith(
                    text: 'A sample response',
                    sources: sources,
                    isStreaming: false,
                  ),
                ],
              ),
            );
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byType(TextField).first,
          'Keep my reflection',
        );
        await tester.tap(find.byType(SourceChip).first);
        await tester.pumpAndSettle();
        expect(find.text('Source 1 of 2'), findsOneWidget);
        await tester.tap(find.byTooltip('Next source'));
        await tester.pumpAndSettle();
        expect(find.text('Source 2 of 2'), findsOneWidget);
        final page = tester.state(find.byType(PageView));
        final passageScroll =
            find
                .descendant(
                  of: find.byType(PageView),
                  matching: find.byType(ListView),
                )
                .last;
        await tester.drag(passageScroll, const Offset(0, -120));
        await tester.pumpAndSettle();
        final scrollState = tester.state<ScrollableState>(
          find
              .descendant(of: passageScroll, matching: find.byType(Scrollable))
              .first,
        );
        final readingOffset = scrollState.position.pixels;
        expect(readingOffset, greaterThan(0));
        tester.view.physicalSize = const Size(669, 951);
        await tester.pumpAndSettle();
        expect(scrollState.position.pixels, readingOffset);
        tester.view.physicalSize = const Size(466, 678);
        await tester.pumpAndSettle();
        expect(find.text('Source 2 of 2'), findsOneWidget);
        expect(tester.state(find.byType(PageView)), same(page));
        expect(scrollState.position.pixels, readingOffset);
        expect(tester.takeException(), isNull);
        tester.view.viewInsets = const FakeViewPadding(bottom: 260);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        tester.view.viewInsets = const FakeViewPadding();
        await tester.binding.handlePopRoute();
        await tester.pumpAndSettle();
        expect(find.text('Source 2 of 2'), findsNothing);
        expect(find.text('Keep my reflection'), findsOneWidget);
        expect(find.text('A sample question'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
