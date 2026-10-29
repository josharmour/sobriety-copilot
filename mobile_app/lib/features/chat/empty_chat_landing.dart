import 'dart:async';

import 'package:flutter/material.dart';

import 'motion_preference_stub.dart'
    if (dart.library.js_interop) 'motion_preference_web.dart';

/// A quiet first-message canvas. The composer stays mounted while idle and
/// entry animations run; no animation changes focus, selection or scroll offset.
class EmptyChatLanding extends StatefulWidget {
  const EmptyChatLanding({
    super.key,
    required this.controller,
    required this.composer,
    required this.prompts,
    required this.onPick,
    required this.active,
    this.footer,
  });

  final TextEditingController controller;
  final Widget composer;
  final List<String> prompts;
  final ValueChanged<String> onPick;
  final bool active;
  final Widget? footer;

  @override
  State<EmptyChatLanding> createState() => _EmptyChatLandingState();
}

class _EmptyChatLandingState extends State<EmptyChatLanding>
    with TickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _entry = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 650),
  );
  late final AnimationController _ideas = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  );
  final _browserMotion = createMotionPreference();
  Timer? _idle;
  bool _visible = false;
  bool _reduceMotion = false;
  bool _foreground = true;
  String _lastText = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _lastText = widget.controller.text;
    widget.controller.addListener(_draftChanged);
    _browserMotion.addListener(_motionChanged);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final media = MediaQuery.of(context);
    _reduceMotion =
        media.disableAnimations ||
        media.accessibleNavigation ||
        _browserMotion.value;
    if (_reduceMotion) {
      _entry.value = 1;
      if (_visible) _ideas.value = 1;
    } else if (widget.active && _entry.value == 0) {
      _entry.forward();
    }
    _scheduleIdeas();
  }

  void _motionChanged() {
    if (!mounted) return;
    final media = MediaQuery.of(context);
    setState(() {
      _reduceMotion =
          media.disableAnimations ||
          media.accessibleNavigation ||
          _browserMotion.value;
      if (_reduceMotion) {
        _entry.value = 1;
        if (_visible) _ideas.value = 1;
      }
    });
  }

  @override
  void didUpdateWidget(EmptyChatLanding oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_draftChanged);
      widget.controller.addListener(_draftChanged);
      _lastText = widget.controller.text;
    }
    if (oldWidget.active != widget.active) {
      _hideIdeas();
      if (widget.active) {
        _reduceMotion ? _entry.value = 1 : _entry.forward(from: 0);
      } else {
        _entry.stop();
      }
      _scheduleIdeas();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _hideIdeas();
    _scheduleIdeas();
  }

  void _draftChanged() {
    // Caret movement and IME selection updates must not restart the idle clock.
    if (_lastText == widget.controller.text) return;
    _lastText = widget.controller.text;
    _hideIdeas();
    _scheduleIdeas();
  }

  void _hideIdeas() {
    _idle?.cancel();
    _idle = null;
    _ideas.stop();
    _ideas.value = 0;
    if (_visible && mounted) setState(() => _visible = false);
  }

  void _scheduleIdeas() {
    if (_idle != null ||
        _visible ||
        !widget.active ||
        !_foreground ||
        widget.controller.text.trim().isNotEmpty) {
      return;
    }
    _idle = Timer(const Duration(milliseconds: 2400), () {
      _idle = null;
      if (!mounted ||
          !widget.active ||
          !_foreground ||
          widget.controller.text.trim().isNotEmpty) {
        return;
      }
      setState(() => _visible = true);
      _reduceMotion ? _ideas.value = 1 : _ideas.forward(from: 0);
    });
  }

  @override
  void dispose() {
    _idle?.cancel();
    _browserMotion.removeListener(_motionChanged);
    _browserMotion.dispose();
    widget.controller.removeListener(_draftChanged);
    WidgetsBinding.instance.removeObserver(this);
    _entry.dispose();
    _ideas.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final reduced = _reduceMotion;
    return DecoratedBox(
      key: const ValueKey('empty-chat-landing'),
      decoration: BoxDecoration(
        gradient: RadialGradient(
          center: const Alignment(0, -0.15),
          radius: 1.05,
          colors: [
            Color.alphaBlend(
              colors.primary.withValues(alpha: .065),
              colors.surface,
            ),
            colors.surface,
          ],
        ),
      ),
      child: LayoutBuilder(
        builder: (context, bounds) {
          final compact = bounds.maxHeight < 480;
          return SingleChildScrollView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: EdgeInsets.symmetric(
              horizontal: bounds.maxWidth < 500 ? 20 : 40,
              vertical: compact ? 20 : 40,
            ),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight: (bounds.maxHeight - (compact ? 40 : 80)).clamp(
                  0,
                  double.infinity,
                ),
              ),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 760),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      AnimatedBuilder(
                        animation: _entry,
                        child: Column(
                          children: [
                            Text(
                              'A little room to think.',
                              textAlign: TextAlign.center,
                              style: theme.textTheme.headlineMedium?.copyWith(
                                fontWeight: FontWeight.w500,
                                letterSpacing: -.7,
                              ),
                            ),
                            const SizedBox(height: 12),
                            Text(
                              'Start anywhere. A question, a feeling, a few words.',
                              textAlign: TextAlign.center,
                              style: theme.textTheme.bodyLarge?.copyWith(
                                color: colors.onSurfaceVariant,
                                height: 1.5,
                              ),
                            ),
                            SizedBox(height: compact ? 24 : 36),
                            widget.composer,
                          ],
                        ),
                        builder: (context, child) {
                          final t = reduced
                              ? 1.0
                              : Curves.easeOutCubic.transform(_entry.value);
                          return Opacity(
                            opacity: t,
                            child: Transform.translate(
                              offset: Offset(0, reduced ? 0 : 12 * (1 - t)),
                              child: child,
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 28),
                      // Reserve the idea area even when invisible. Appearing and
                      // dismissing prompts never shifts the composer or the page.
                      IgnorePointer(
                        ignoring: !_visible,
                        child: ExcludeFocus(
                          excluding: !_visible,
                          child: ExcludeSemantics(
                            excluding: !_visible,
                            child: AnimatedBuilder(
                              animation: _ideas,
                              builder: (context, _) => Column(
                                children: [
                                  Opacity(
                                    opacity: _ideas.value,
                                    child: Text(
                                      'A thought to start with',
                                      style: theme.textTheme.labelMedium
                                          ?.copyWith(
                                            color: colors.onSurfaceVariant,
                                          ),
                                    ),
                                  ),
                                  const SizedBox(height: 14),
                                  Wrap(
                                    alignment: WrapAlignment.center,
                                    spacing: 12,
                                    runSpacing: 12,
                                    children: [
                                      for (
                                        var i = 0;
                                        i < widget.prompts.take(3).length;
                                        i++
                                      )
                                        Builder(
                                          builder: (context) {
                                            final t = reduced
                                                ? _ideas.value
                                                : Interval(
                                                    i * .18,
                                                    .64 + i * .18,
                                                    curve: Curves.easeOutCubic,
                                                  ).transform(_ideas.value);
                                            return Opacity(
                                              opacity: t,
                                              child: Transform.translate(
                                                offset: Offset(
                                                  0,
                                                  reduced ? 0 : 8 * (1 - t),
                                                ),
                                                child: ConstrainedBox(
                                                  constraints:
                                                      const BoxConstraints(
                                                        maxWidth: 330,
                                                      ),
                                                  child: OutlinedButton(
                                                    key: ValueKey(
                                                      'thought-bubble-$i',
                                                    ),
                                                    onPressed: _visible
                                                        ? () => widget.onPick(
                                                            widget.prompts[i],
                                                          )
                                                        : null,
                                                    style: OutlinedButton.styleFrom(
                                                      animationDuration: reduced
                                                          ? Duration.zero
                                                          : const Duration(
                                                              milliseconds: 180,
                                                            ),
                                                      foregroundColor:
                                                          colors.onSurface,
                                                      backgroundColor: colors
                                                          .surface
                                                          .withValues(
                                                            alpha: .65,
                                                          ),
                                                      side: BorderSide(
                                                        color: colors
                                                            .outlineVariant
                                                            .withValues(
                                                              alpha: .75,
                                                            ),
                                                      ),
                                                      minimumSize: const Size(
                                                        48,
                                                        48,
                                                      ),
                                                      padding:
                                                          const EdgeInsets.symmetric(
                                                            horizontal: 20,
                                                            vertical: 15,
                                                          ),
                                                      shape: RoundedRectangleBorder(
                                                        borderRadius: BorderRadius.only(
                                                          topLeft:
                                                              const Radius.circular(
                                                                24,
                                                              ),
                                                          topRight:
                                                              const Radius.circular(
                                                                24,
                                                              ),
                                                          bottomLeft:
                                                              Radius.circular(
                                                                i.isEven
                                                                    ? 8
                                                                    : 24,
                                                              ),
                                                          bottomRight:
                                                              Radius.circular(
                                                                i.isEven
                                                                    ? 24
                                                                    : 8,
                                                              ),
                                                        ),
                                                      ),
                                                    ),
                                                    child: Text(
                                                      widget.prompts[i],
                                                      textAlign:
                                                          TextAlign.center,
                                                      style: theme
                                                          .textTheme
                                                          .bodyMedium
                                                          ?.copyWith(
                                                            height: 1.4,
                                                          ),
                                                    ),
                                                  ),
                                                ),
                                              ),
                                            );
                                          },
                                        ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                      if (widget.footer != null) ...[
                        const SizedBox(height: 24),
                        widget.footer!,
                      ],
                    ],
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
