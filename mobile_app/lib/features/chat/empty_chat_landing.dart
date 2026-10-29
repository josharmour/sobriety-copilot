import 'dart:async';
import 'package:flutter/material.dart';
import 'motion_preference_stub.dart'
    if (dart.library.js_interop) 'motion_preference_web.dart';

/// The first-message canvas. A bounded rotating set sits beneath an anchored composer;
/// they never request focus, change selection, or scroll the page.
class EmptyChatLanding extends StatefulWidget {
  const EmptyChatLanding({
    super.key,
    required this.controller,
    required this.composer,
    required this.prompts,
    required this.onPick,
    required this.active,
    this.loadPrompts,
    this.footer,
  });

  final TextEditingController controller;
  final Widget composer;

  /// Offline fallback (and a deterministic pool for widget tests).
  final List<String> prompts;

  /// Existing synchronous, bundled catalog picker; no per-bubble network calls.
  final List<String> Function(int count, Set<String> alreadyShown)? loadPrompts;
  final ValueChanged<String> onPick;
  final bool active;
  final Widget? footer;
  static const maxSuggestions = 5;

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
    reverseDuration: const Duration(milliseconds: 450),
  );
  final _browserMotion = createMotionPreference();
  final List<String> _suggestions = [];
  Timer? _idle;
  int _batchStart = 0;
  int _cap = 3;
  int _nextSlot = 0;
  int? _swapIndex;
  bool _changing = false;
  bool _screenReader = false;
  final Set<int> _hovered = {};
  final Set<int> _focused = {};
  Set<int> get _protected => {..._hovered, ..._focused};
  final List<String> _recent = [];
  bool _visible = false;
  bool _picked = false;
  bool _exhausted = false;
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

  void _readMotionPreference() {
    final media = MediaQuery.of(context);
    _screenReader = media.accessibleNavigation;
    if (_screenReader && _visible) {
      _idle?.cancel();
      _idle = null;
    }
    _reduceMotion =
        media.disableAnimations ||
        media.accessibleNavigation ||
        _browserMotion.value;
    if (_reduceMotion) {
      _entry.value = 1;
      if (_visible) _ideas.value = 1;
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _readMotionPreference();
    final nextCap = MediaQuery.sizeOf(context).width < 700 ? 3 : 5;
    if (nextCap != _cap) {
      _hideIdeas();
      _hovered.clear();
      _focused.clear();
      _cap = nextCap;
    }
    if (_suggestions.length > _cap) {
      _suggestions.removeRange(_cap, _suggestions.length);
    }
    _nextSlot %= _cap;
    if (!_reduceMotion && widget.active && _entry.value == 0) _entry.forward();
    _prepareInitial();
    _scheduleIdeas();
  }

  void _motionChanged() {
    if (mounted) setState(_readMotionPreference);
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
      _prepareInitial();
      _scheduleIdeas();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _hideIdeas();
    _scheduleIdeas();
  }

  void _prepareInitial() {
    if (widget.active && _suggestions.isEmpty && !_exhausted) _loadBatch(3);
  }

  List<String> _draw(int count) {
    final seen = {
      ..._recent,
      ..._suggestions,
    }.map((p) => p.trim().toLowerCase()).toSet();
    List<String> candidates;
    try {
      candidates =
          widget.loadPrompts?.call(count, {..._recent, ..._suggestions}) ??
          widget.prompts;
    } catch (_) {
      candidates = widget.prompts;
    }
    final result = <String>[];
    for (final raw in [...candidates, ...widget.prompts]) {
      if (result.length >= count) break;
      final prompt = raw.trim();
      if (prompt.isNotEmpty && seen.add(prompt.toLowerCase())) {
        result.add(prompt);
      }
    }
    if (result.isNotEmpty) _exhausted = false;
    _recent.addAll(result);
    if (_recent.length > 240) _recent.removeRange(0, _recent.length - 240);
    return result;
  }

  int _loadBatch(int count) {
    final added = _draw(count.clamp(0, _cap - _suggestions.length));
    _suggestions.addAll(added);
    if (added.isEmpty) _exhausted = true;
    return added.length;
  }

  void _protect(int slot, bool value, {bool focus = false}) {
    final targets = focus ? _focused : _hovered;
    value ? targets.add(slot) : targets.remove(slot);
    if (value && _changing) {
      // If the pointer or focus enters an outgoing choice, restore it and
      // cancel that replacement. Its label and target remain the same.
      _ideas.stop();
      _ideas.value = 1;
      if (mounted) setState(() => _swapIndex = null);
    }
  }

  void _draftChanged() {
    // Caret movement / IME selection alone must not restart the idle clock.
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
    _swapIndex = null;
    if (_visible && mounted) setState(() => _visible = false);
  }

  bool get _canShow =>
      !_picked &&
      widget.active &&
      _foreground &&
      widget.controller.text.trim().isEmpty;

  void _scheduleIdeas() {
    if (_idle != null ||
        _changing ||
        !_canShow ||
        (_visible && (_exhausted || _screenReader))) {
      return;
    }
    _idle = Timer(
      _visible
          ? const Duration(seconds: 7)
          : const Duration(milliseconds: 2400),
      () {
        _idle = null;
        if (!mounted || !_canShow) return;
        if (!_visible) {
          setState(() {
            _batchStart = 0;
            _visible = true;
          });
          _reduceMotion ? _ideas.value = 1 : _ideas.forward(from: 0);
          _scheduleIdeas();
        } else {
          unawaited(_advanceIdeas());
        }
      },
    );
  }

  Future<void> _advanceIdeas() async {
    if (!_canShow || !_visible || _changing) return;
    if (_protected.isNotEmpty) {
      _scheduleIdeas();
      return;
    }
    _idle?.cancel();
    _idle = null;
    _changing = true;
    try {
      if (_suggestions.length < _cap) {
        final before = _suggestions.length;
        final added = _loadBatch(_cap - before);
        if (added > 0) {
          setState(() {
            _swapIndex = null;
            _batchStart = before;
          });
          if (_reduceMotion) {
            _ideas.value = 1;
          } else {
            await _ideas.forward(from: 0).orCancel;
          }
          return;
        }
      }
      if (_suggestions.isEmpty) return;
      final slot = _nextSlot % _suggestions.length;
      setState(() => _swapIndex = slot);
      if (_reduceMotion) {
        _ideas.value = 0;
      } else {
        await _ideas.reverse(from: 1).orCancel;
      }
      if (!mounted || !_canShow || _protected.isNotEmpty) return;
      final next = _draw(1);
      if (next.isEmpty) {
        _exhausted = true;
        _ideas.value = 1;
        return;
      }
      setState(() {
        _suggestions[slot] = next.single;
        _nextSlot = (slot + 1) % _cap;
      });
      if (_reduceMotion) {
        _ideas.value = 1;
      } else {
        await _ideas.forward(from: 0).orCancel;
      }
    } on TickerCanceled {
      // Typing, sending, tab changes and disposal cancel an in-progress fade.
    } finally {
      if (mounted) {
        setState(() {
          _changing = false;
          _swapIndex = null;
          _batchStart = _suggestions.length;
        });
        _scheduleIdeas();
      }
    }
  }

  void _pick(String prompt) {
    // Synchronous latch also rejects already-queued tap/keyboard callbacks
    // before the parent's conversation state has rebuilt this view away.
    if (_picked ||
        !_visible ||
        !widget.active ||
        widget.controller.text.trim().isNotEmpty) {
      return;
    }
    _picked = true;
    _hideIdeas();
    widget.onPick(prompt);
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

  Widget _thoughts(ThemeData theme) {
    final colors = theme.colorScheme;
    return IgnorePointer(
      ignoring: !_visible,
      child: ExcludeFocus(
        excluding: !_visible,
        child: ExcludeSemantics(
          excluding: !_visible,
          child: AnimatedBuilder(
            animation: _ideas,
            builder: (context, _) {
              return Column(
                children: [
                  Opacity(
                    opacity: !_visible
                        ? 0
                        : (_batchStart == 0 && _swapIndex == null
                              ? _ideas.value
                              : 1),
                    child: Text(
                      _suggestions.isEmpty
                          ? 'No suggestions right now. You can still start anywhere.'
                          : 'A thought to start with',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.labelMedium?.copyWith(
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
                      for (var i = 0; i < _suggestions.length; i++)
                        Builder(
                          builder: (context) {
                            final local = (i - _batchStart).clamp(0, 2);
                            final t = !_visible
                                ? 0.0
                                : _swapIndex != null
                                ? (i == _swapIndex
                                      ? Curves.easeOutCubic.transform(
                                          _ideas.value,
                                        )
                                      : 1.0)
                                : i < _batchStart
                                ? 1.0
                                : _reduceMotion
                                ? _ideas.value
                                : Interval(
                                    local * .18,
                                    .64 + local * .18,
                                    curve: Curves.easeOutCubic,
                                  ).transform(_ideas.value);
                            return Opacity(
                              opacity: t,
                              child: Transform.translate(
                                offset: Offset(
                                  0,
                                  _reduceMotion ? 0 : 8 * (1 - t),
                                ),
                                child: ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 330,
                                  ),
                                  child: Focus(
                                    canRequestFocus: false,
                                    onFocusChange: (focused) =>
                                        _protect(i, focused, focus: true),
                                    child: MouseRegion(
                                      onEnter: (_) => _protect(i, true),
                                      onExit: (_) => _protect(i, false),
                                      child: OutlinedButton(
                                        key: ValueKey('thought-bubble-$i'),
                                        onPressed: _visible && !_picked
                                            ? () => _pick(_suggestions[i])
                                            : null,
                                        style: OutlinedButton.styleFrom(
                                          animationDuration: _reduceMotion
                                              ? Duration.zero
                                              : const Duration(
                                                  milliseconds: 180,
                                                ),
                                          foregroundColor: colors.onSurface,
                                          backgroundColor: colors.surface
                                              .withValues(alpha: .65),
                                          side: BorderSide(
                                            color: colors.outlineVariant
                                                .withValues(alpha: .75),
                                          ),
                                          minimumSize: const Size(48, 48),
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 20,
                                            vertical: 15,
                                          ),
                                          shape: RoundedRectangleBorder(
                                            borderRadius: BorderRadius.only(
                                              topLeft: const Radius.circular(
                                                24,
                                              ),
                                              topRight: const Radius.circular(
                                                24,
                                              ),
                                              bottomLeft: Radius.circular(
                                                i.isEven ? 8 : 24,
                                              ),
                                              bottomRight: Radius.circular(
                                                i.isEven ? 24 : 8,
                                              ),
                                            ),
                                          ),
                                        ),
                                        child: Text(
                                          _suggestions[i],
                                          textAlign: TextAlign.center,
                                          style: theme.textTheme.bodyMedium
                                              ?.copyWith(height: 1.4),
                                        ),
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
                  if (_suggestions.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Opacity(
                        opacity: _visible ? 1 : 0,
                        child: TextButton(
                          onPressed: _visible && !_changing
                              ? () => unawaited(_advanceIdeas())
                              : null,
                          child: const Text('More ideas'),
                        ),
                      ),
                    ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return DecoratedBox(
      key: const ValueKey('empty-chat-landing'),
      decoration: BoxDecoration(
        gradient: RadialGradient(
          center: const Alignment(0, -.15),
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
          final narrow = bounds.maxWidth < 500;
          // Anchor the composer independently of the number of bubbles. Changing
          // questions never recenter the writing area or scroll it automatically.
          final topSpace = compact
              ? 0.0
              : ((bounds.maxHeight - (narrow ? 600 : 530)) / 2).clamp(
                  0.0,
                  140.0,
                );
          return SingleChildScrollView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: EdgeInsets.symmetric(
              horizontal: narrow ? 20 : 40,
              vertical: compact ? 20 : 40,
            ),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight: (bounds.maxHeight - (compact ? 40 : 80)).clamp(
                  0,
                  double.infinity,
                ),
              ),
              child: Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 760),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SizedBox(height: topSpace),
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
                          final t = _reduceMotion
                              ? 1.0
                              : Curves.easeOutCubic.transform(_entry.value);
                          return Opacity(
                            opacity: t,
                            child: Transform.translate(
                              offset: Offset(
                                0,
                                _reduceMotion ? 0 : 12 * (1 - t),
                              ),
                              child: child,
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 28),
                      _thoughts(theme),
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
