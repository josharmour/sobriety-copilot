import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sobriety_copilot_mobile/features/layout/app_safe_viewport.dart';

void main() {
  testWidgets(
    'reserves asymmetric sides across folds without resetting draft',
    (tester) async {
      final controller = TextEditingController();
      addTearDown(controller.dispose);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      tester.view.devicePixelRatio = 1;
      Future<void> layout(
        Size size,
        EdgeInsets sides, {
        double keyboard = 0,
      }) async {
        tester.view.physicalSize = size;
        await tester.pumpWidget(
          MaterialApp(
            builder:
                (context, child) => MediaQuery(
                  data: MediaQueryData(
                    size: size,
                    padding: sides,
                    viewPadding: sides,
                    viewInsets: EdgeInsets.only(bottom: keyboard),
                  ),
                  child: AppSafeViewport(child: child!),
                ),
            home: Scaffold(
              appBar: AppBar(title: const Text('Copilot')),
              body: Column(
                children: [
                  const Expanded(
                    child: SizedBox.expand(key: ValueKey('messages')),
                  ),
                  SafeArea(
                    top: false,
                    child: TextField(controller: controller),
                  ),
                ],
              ),
              bottomNavigationBar: const SafeArea(
                top: false,
                child: SizedBox(
                  height: 60,
                  width: double.infinity,
                  key: ValueKey('navigation'),
                ),
              ),
            ),
          ),
        );
        await tester.pump();
        final content = tester.getRect(find.byKey(const ValueKey('messages')));
        final input = tester.getRect(find.byType(TextField));
        final navigation = tester.getRect(
          find.byKey(const ValueKey('navigation')),
        );
        expect(content.left, sides.left);
        expect(content.right, size.width - sides.right);
        expect(input.left, content.left);
        expect(input.right, content.right);
        expect(navigation.left, content.left);
        expect(navigation.right, content.right);
        expect(input.bottom, lessThanOrEqualTo(size.height - keyboard));
        expect(tester.takeException(), isNull);
      }

      await layout(const Size(466, 678), const EdgeInsets.only(right: 84));
      await tester.enterText(find.byType(TextField), 'Keep this reflection');
      controller.selection = const TextSelection.collapsed(offset: 5);
      await layout(const Size(951, 669), const EdgeInsets.only(left: 84));
      expect(controller.text, 'Keep this reflection');
      expect(controller.selection.baseOffset, 5);
      await layout(
        const Size(466, 678),
        const EdgeInsets.only(right: 84),
        keyboard: 250,
      );
      expect(controller.text, 'Keep this reflection');
      await layout(const Size(390, 844), EdgeInsets.zero);
    },
  );

  testWidgets('side protection also surrounds pushed reader routes', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        builder:
            (context, child) => MediaQuery(
              data: const MediaQueryData(
                padding: EdgeInsets.only(left: 45, right: 80),
              ),
              child: AppSafeViewport(child: child!),
            ),
        home: Builder(
          builder:
              (context) => Scaffold(
                body: TextButton(
                  onPressed:
                      () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder:
                              (_) => const Scaffold(
                                body: SizedBox.expand(key: ValueKey('reader')),
                              ),
                        ),
                      ),
                  child: const Text('Read'),
                ),
              ),
        ),
      ),
    );
    await tester.tap(find.text('Read'));
    await tester.pumpAndSettle();
    final bounds = tester.getRect(find.byKey(const ValueKey('reader')));
    expect(bounds.left, 45);
    expect(bounds.right, 720);
    expect(tester.takeException(), isNull);
  });
}
