import 'package:flutter/material.dart';

/// Keeps every route inside horizontal system UI, including Duo's side status
/// region. Scaffold does not automatically inset its body on the left/right.
/// SafeArea consumes the padding so nested bars and composers do not apply it
/// twice. Top/bottom and keyboard handling remain owned by the route widgets.
class AppSafeViewport extends StatelessWidget {
  const AppSafeViewport({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: Theme.of(context).scaffoldBackgroundColor,
    child: SafeArea(top: false, bottom: false, child: child),
  );
}
