/// FR9 meditation library + player bottom sheet.
///
/// Two states: a library list of curated sessions, and a live player for the
/// active session. Visual cues (expanding circle + countdown) are the source of
/// truth; spoken step labels are an opt-in toggle. The player pauses on app
/// background via a [WidgetsBindingObserver] and resumes manually by the user.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/meditation/player.dart';
import 'package:sobriety_copilot_mobile/features/meditation/session.dart';
import 'package:sobriety_copilot_mobile/features/sheets/crisis_sheet.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

const String kCrisisNoteText =
    'Not a substitute for emergency help — see the crisis sheet';

String _fmtDuration(int seconds) {
  final m = seconds ~/ 60;
  final s = seconds % 60;
  return m > 0 ? '${m}m ${s}s' : '${s}s';
}

/// Library picker + player sheet.
class MeditationSheet extends ConsumerStatefulWidget {
  const MeditationSheet({super.key});

  @override
  ConsumerState<MeditationSheet> createState() => _MeditationSheetState();
}

class _MeditationSheetState extends ConsumerState<MeditationSheet>
    with WidgetsBindingObserver {
  MedTts? _tts;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Capture the TTS instance now; `ref` is invalid in dispose().
    _tts = ref.read(medTtsProvider);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    // Silence any in-progress cue when the sheet closes (rule 3).
    _tts?.stop();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Don't let the timer run in the background; resume manually (rule 6).
    if (state == AppLifecycleState.paused) {
      ref.read(meditationPlayerProvider.notifier).pause();
    }
  }

  @override
  Widget build(BuildContext context) {
    final playing = ref.watch(
      meditationPlayerProvider.select((s) => s.session != null),
    );
    return SafeArea(
      top: false,
      child: playing ? const _PlayerView() : const _LibraryView(),
    );
  }
}

/// List of curated sessions. "Surf the Urge" is first with a crisis-sheet link.
class _LibraryView extends ConsumerWidget {
  const _LibraryView();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: Row(
            children: [
              const Icon(Icons.self_improvement_outlined),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text('Meditation', style: theme.textTheme.titleLarge),
              ),
              IconButton(
                icon: const Icon(Icons.close),
                tooltip: 'Close',
                onPressed: () => Navigator.of(context).maybePop(),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.md,
              AppSpacing.lg,
              AppSpacing.xxl,
            ),
            children: [
              for (final s in kMeditations) ...[
                _SessionTile(session: s),
                const SizedBox(height: AppSpacing.md),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _SessionTile extends ConsumerWidget {
  const _SessionTile({required this.session});
  final MeditationSession session;

  void _openCrisis(BuildContext context) {
    Navigator.of(context).pop();
    showAppSheet(context, const CrisisSheet());
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final isSurf = session.id == 'surf_urge';
    final icon =
        isSurf ? Icons.waves : Icons.self_improvement_outlined;

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        onTap: () => ref.read(meditationPlayerProvider.notifier).load(session),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
              Icon(icon, size: 28, color: theme.colorScheme.primary),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      session.title,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      session.description,
                      style: theme.textTheme.bodyMedium,
                    ),
                    if (isSurf) ...[
                      const SizedBox(height: AppSpacing.xs),
                      InkWell(
                        onTap: () => _openCrisis(context),
                        child: Text(
                          kCrisisNoteText,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.primary,
                            decoration: TextDecoration.underline,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      '${_fmtDuration(session.totalSeconds)} · '
                      '${session.cycles} cycle${session.cycles == 1 ? '' : 's'}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}

/// Live player: breathing circle + countdown + controls + TTS toggle.
class _PlayerView extends ConsumerStatefulWidget {
  const _PlayerView();

  @override
  ConsumerState<_PlayerView> createState() => _PlayerViewState();
}

class _PlayerViewState extends ConsumerState<_PlayerView>
    with SingleTickerProviderStateMixin {
  late final AnimationController _circle;

  @override
  void initState() {
    super.initState();
    _circle = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat(reverse: true);
    // Auto-start on load (the user just tapped a session).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final p = ref.read(meditationPlayerProvider.notifier);
      final s = ref.read(meditationPlayerProvider);
      if (!s.running && s.session != null) p.start();
    });
  }

  @override
  void dispose() {
    _circle.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = ref.watch(meditationPlayerProvider);
    final session = state.session!;
    final label = state.currentLabel ?? '';
    final secondsLeft = state.secondsLeft;
    final isTtsEnabled = ref
        .read(meditationPlayerProvider.notifier)
        .ttsEnabled;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: Row(
            children: [
              const Icon(Icons.self_improvement_outlined),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(session.title, style: theme.textTheme.titleLarge),
              ),
              IconButton(
                icon: const Icon(Icons.close),
                tooltip: 'Close',
                onPressed: () async {
                  await ref.read(meditationPlayerProvider.notifier).stop();
                  if (context.mounted) Navigator.of(context).maybePop();
                },
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Breathing circle with a screen-reader text fallback (rule 9).
              Semantics(
                label: '$label, $secondsLeft seconds',
                liveRegion: true,
                child: ExcludeSemantics(
                  child: AnimatedBuilder(
                    animation: _circle,
                    builder: (context, _) {
                      final size = 180.0 + (_circle.value * 120.0);
                      return Container(
                        width: size,
                        height: size,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: theme.colorScheme.primary
                              .withValues(alpha: 0.18),
                          border: Border.all(
                            color: theme.colorScheme.primary,
                            width: 2,
                          ),
                        ),
                        alignment: Alignment.center,
                        child: Text(
                          label,
                          textAlign: TextAlign.center,
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              Text('$label · $secondsLeft', style: theme.textTheme.titleMedium),
              const SizedBox(height: AppSpacing.lg),
              Text(
                'Step ${state.stepIndex + 1} of ${session.steps.length} · '
                'Cycle ${state.cycle + 1} of ${session.cycles}',
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: AppSpacing.xl),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    icon: Icon(
                      state.running
                          ? Icons.pause_circle_outline
                          : Icons.play_circle_outline,
                      size: 56,
                    ),
                    tooltip: state.running ? 'Pause' : 'Resume',
                    onPressed: () {
                      final p = ref.read(meditationPlayerProvider.notifier);
                      state.running ? p.pause() : p.resume();
                    },
                  ),
                  const SizedBox(width: AppSpacing.lg),
                  IconButton(
                    icon: const Icon(Icons.stop_circle_outlined, size: 56),
                    tooltip: 'Stop',
                    onPressed: () async {
                      await ref.read(meditationPlayerProvider.notifier).stop();
                    },
                  ),
                ],
              ),
            ],
          ),
        ),
        SwitchListTile(
          dense: true,
          value: isTtsEnabled,
          title: const Text('Speak step cues'),
          subtitle: const Text('An on-device voice reads each step label.'),
          onChanged: (v) async {
            await ref
                .read(meditationPlayerProvider.notifier)
                .setTtsEnabled(v);
            if (mounted) setState(() {});
          },
        ),
        const SizedBox(height: AppSpacing.lg),
      ],
    );
  }
}
