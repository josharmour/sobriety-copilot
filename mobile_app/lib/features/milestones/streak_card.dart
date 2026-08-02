/// FR5 — the check-in streak card on the Today sheet: the single user-facing
/// streak (consecutive days the user showed up for themselves).
///
/// Calm by design: no flames or gamification iconography, no loss-framing
/// when a streak breaks, and no recovery wording anywhere — so the card is
/// discreet-safe and renders unchanged in discreet mode.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/milestones/streak.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

class StreakCard extends ConsumerWidget {
  const StreakCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(streakProvider);
    final theme = Theme.of(context);
    final today = DateTime.now();
    final checkedToday = s.checkedIn(today) &&
        s.lastCheckIn != null &&
        s.current > 0;

    // Never show what was lost: a fresh day-1 after a longer best is greeted,
    // not mourned.
    final String headline;
    if (s.current == 0) {
      headline = s.best > 0
          ? "A new streak starts whenever you're ready."
          : 'Show up for yourself today.';
    } else if (s.current == 1 && s.best > 1) {
      headline = 'Welcome back — day 1 of a new streak.';
    } else if (s.current == 1) {
      headline = 'Day 1 — you showed up for yourself today.';
    } else {
      headline = 'You showed up for yourself ${s.current} days in a row.';
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.spa_outlined,
                    size: 20, color: theme.colorScheme.primary),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    'Check-in streak',
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                if (s.best > 0)
                  Text(
                    'Best: ${s.best} ${s.best == 1 ? 'day' : 'days'}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(headline, style: theme.textTheme.bodyMedium),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                _WeekDots(state: s, today: today),
                const Spacer(),
                if (checkedToday)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.check_circle_outline,
                          size: 18, color: AppColors.accent),
                      const SizedBox(width: AppSpacing.xs),
                      Text(
                        'Checked in',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  )
                else
                  FilledButton.tonal(
                    onPressed: () => ref
                        .read(streakProvider.notifier)
                        .recordCheckIn(),
                    child: const Text('Check in'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// The last seven days as small dots, today rightmost. Purely ambient — the
/// count lives in the headline, so the dots are excluded from semantics in
/// favor of one summary label.
class _WeekDots extends StatelessWidget {
  final StreakState state;
  final DateTime today;

  const _WeekDots({required this.state, required this.today});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    var checkIns = 0;
    final dots = <Widget>[];
    for (var i = 6; i >= 0; i--) {
      final day = DateTime(today.year, today.month, today.day - i);
      final filled = state.checkedIn(day);
      if (filled) checkIns++;
      dots.add(Container(
        width: 10,
        height: 10,
        margin: const EdgeInsets.only(right: AppSpacing.xs),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: filled
              ? AppColors.accent
              : theme.colorScheme.surfaceContainerHighest,
          border: Border.all(color: theme.colorScheme.outlineVariant),
        ),
      ));
    }
    return Semantics(
      label: 'Last 7 days: $checkIns '
          '${checkIns == 1 ? 'check-in' : 'check-ins'}',
      child: ExcludeSemantics(child: Row(children: dots)),
    );
  }
}
