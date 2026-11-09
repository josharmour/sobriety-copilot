import 'package:flutter/material.dart';

/// The same chat and reader subtrees stay mounted through a fold. Wide windows
/// show both; compact windows show the reader over chat until it is dismissed.
/// Layout uses the route's usable constraints, never a device model or idiom.
class AdaptiveReadingWorkspace extends StatelessWidget {
  const AdaptiveReadingWorkspace({
    super.key,
    required this.child,
    required this.reader,
    required this.onClose,
  });

  final Widget child;
  final Widget? reader;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, size) {
      // Leave enough readable space per pane; larger text uses a single pane.
      final wide =
          size.maxWidth >= 760 &&
          MediaQuery.textScalerOf(context).scale(16) <= 24;
      final shown = reader != null;
      final readerWidth =
          wide ? (size.maxWidth * .44).clamp(320.0, 480.0) : size.maxWidth;
      return PopScope(
        canPop: !shown,
        onPopInvokedWithResult: (didPop, result) {
          if (!didPop && shown) onClose();
        },
        child: Stack(
          children: [
            Positioned.fill(
              right: shown && wide ? readerWidth : 0,
              child: ExcludeFocus(
                excluding: shown && !wide,
                child: ExcludeSemantics(
                  excluding: shown && !wide,
                  child: IgnorePointer(ignoring: shown && !wide, child: child),
                ),
              ),
            ),
            if (shown)
              Positioned(
                top: 0,
                bottom: 0,
                right: 0,
                width: readerWidth,
                child: Material(
                  color: Theme.of(context).colorScheme.surface,
                  shape: Border(
                    left: BorderSide(color: Theme.of(context).dividerColor),
                  ),
                  child: Semantics(
                    container: true,
                    explicitChildNodes: true,
                    label: 'Reading pane',
                    child: reader!,
                  ),
                ),
              ),
          ],
        ),
      );
    },
  );
}
