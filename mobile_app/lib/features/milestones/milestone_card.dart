import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import 'package:sobriety_copilot_mobile/config/capabilities.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/features/sheets/crisis_sheet.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Milestone card shown on the conversation starter view. Styled to match
/// the daily-reflection container (translucent over the hero image).
class MilestoneCard extends ConsumerWidget {
  const MilestoneCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(sobrietyProvider);
    final theme = Theme.of(context);
    final isLight = theme.brightness == Brightness.light;

    final textColor = isLight ? theme.colorScheme.onSurface : Colors.white;
    final subtextColor = isLight ? theme.colorScheme.onSurfaceVariant : Colors.white70;
    final mutedIconColor = isLight ? theme.colorScheme.onSurfaceVariant : Colors.white38;

    final decoration = BoxDecoration(
      color: isLight
          ? theme.colorScheme.surface
          : Colors.black.withAlpha(120),
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      border: Border.all(
        color: isLight
            ? theme.colorScheme.outlineVariant
            : Colors.white24,
      ),
      boxShadow: isLight
          ? [
              BoxShadow(
                color: Colors.black.withAlpha(12),
                blurRadius: 8,
                offset: const Offset(0, 2),
              ),
            ]
          : null,
    );

    if (!state.isTracking) {
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 600),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppSpacing.radius),
            onTap: () => showTrackerEditor(context, ref),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: decoration,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.emoji_events_outlined,
                      color: subtextColor, size: 20),
                  const SizedBox(width: AppSpacing.sm),
                  Text(
                    'Track your sober time',
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: subtextColor),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    final days = state.daysSober;
    final next = state.nextMilestone;
    final last = state.lastMilestone;
    final toGo = next.days - days;
    final saved = state.moneySaved;

    if (state.discreet) {
      return Center(
        child: InkWell(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
          onTap: () => showTrackerEditor(context, ref),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.md,
              vertical: AppSpacing.sm,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: (last ?? next).color,
                    border: Border.all(color: mutedIconColor),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  'Day $days',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: subtextColor,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(width: AppSpacing.xs),
                Icon(Icons.edit_outlined,
                    color: mutedIconColor, size: 14),
              ],
            ),
          ),
        ),
      );
    }

    final headline = days == 0
        ? 'Day one'
        : '$days ${days == 1 ? 'day' : 'days'} sober';
    final subtitle = '$toGo ${toGo == 1 ? 'day' : 'days'} to ${next.label}'
        '${saved != null ? '  ·  ${NumberFormat.simpleCurrency().format(saved)} saved' : ''}';

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 600),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
          onTap: () => showTrackerEditor(context, ref),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: decoration,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 14,
                      height: 14,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: (last ?? next).color,
                        border: Border.all(color: mutedIconColor),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        headline,
                        style: theme.textTheme.titleLarge?.copyWith(
                          color: textColor,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    Icon(Icons.edit_outlined,
                        color: mutedIconColor, size: 16),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  subtitle,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: subtextColor),
                ),
                const SizedBox(height: AppSpacing.sm),
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: state.milestoneProgress,
                    minHeight: 5,
                    backgroundColor: isLight ? theme.colorScheme.outlineVariant : Colors.white24,
                    color: AppColors.accent,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Bottom-sheet editor: set/change the sobriety date, discreet mode, and the
/// optional daily-spend estimate for the money-saved line.
Future<void> showTrackerEditor(BuildContext context, WidgetRef ref) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (sheetContext) => const _TrackerEditorSheet(),
  );
}

class _TrackerEditorSheet extends ConsumerStatefulWidget {
  const _TrackerEditorSheet();

  @override
  ConsumerState<_TrackerEditorSheet> createState() =>
      _TrackerEditorSheetState();
}

class _TrackerEditorSheetState extends ConsumerState<_TrackerEditorSheet> {
  late final TextEditingController _spendController;

  @override
  void initState() {
    super.initState();
    final cents = ref.read(sobrietyProvider).dailySpendCents;
    _spendController = TextEditingController(
      text: cents == null ? '' : (cents / 100).toStringAsFixed(2),
    );
  }

  @override
  void dispose() {
    _spendController.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final state = ref.read(sobrietyProvider);
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: state.sobrietyDate ?? now,
      firstDate: DateTime(1950),
      lastDate: now,
      helpText: 'First day sober',
    );
    if (picked != null) {
      await ref.read(sobrietyProvider.notifier).setDate(picked);
    }
  }

  Future<void> _saveSpend() async {
    final raw = _spendController.text.trim().replaceAll(r'$', '');
    final dollars = double.tryParse(raw);
    await ref.read(sobrietyProvider.notifier).setDailySpend(dollars);
  }

  /// Shows the relapse-log dialog, then surfaces the supportive confirmation
  /// (and crisis link) inside this sheet once it is confirmed — so the message
  /// is visible and the link works (the sheet's context stays alive, unlike a
  /// snackbar shown after the modal is dismissed).
  bool _showSupport = false;

  Future<void> _onSlipped() async {
    final confirmed = await showRelapseLogDialog(
      context,
      ref,
      discreet: ref.read(sobrietyProvider).discreet,
    );
    if (confirmed && mounted) {
      setState(() => _showSupport = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(sobrietyProvider);
    final theme = Theme.of(context);
    final dateLabel = state.sobrietyDate == null
        ? 'Not set'
        : DateFormat.yMMMMd().format(state.sobrietyDate!);

    return SafeArea(
      top: false,
      child: SingleChildScrollView(
        padding: EdgeInsets.only(
          left: AppSpacing.lg,
          right: AppSpacing.lg,
          top: AppSpacing.sm,
          bottom:
              MediaQuery.of(context).viewInsets.bottom + AppSpacing.lg,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Recovery tracker',
              style: theme.textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Stored only on this device. Never sent anywhere.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: AppSpacing.sm),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event_outlined),
              title: const Text('Sobriety date'),
              subtitle: Text(dateLabel),
              trailing: const Icon(Icons.chevron_right),
              onTap: _pickDate,
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: state.discreet,
              title: const Text('Discreet display'),
              subtitle: Text(
                supportsHomeWidget
                    ? 'Show "Day 92" with no recovery wording — here and on '
                        'the home-screen widget.'
                    : 'Show "Day 92" with no recovery wording.',
              ),
              onChanged: (v) =>
                  ref.read(sobrietyProvider.notifier).setDiscreet(v),
            ),
            TextField(
              controller: _spendController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              onSubmitted: (_) => _saveSpend(),
              onTapOutside: (_) => _saveSpend(),
              decoration: const InputDecoration(
                isDense: true,
                prefixText: r'$ ',
                labelText: 'Estimated daily spend (optional)',
                helperText: 'Shows how much you have saved. Leave blank to hide.',
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            // History (and its erase controls) stays reachable even after the
            // user stops tracking — notes must never become undeletable, and
            // the preserved streak record must stay erasable too.
            if (state.relapses.isNotEmpty || state.bestStreakDays > 0) ...[
              _HistorySection(discreet: state.discreet),
              const SizedBox(height: AppSpacing.md),
            ],
            if (state.isTracking)
              // Deliberately NOT delete-styled: stopping the counter keeps
              // all history on the device, and the dialog says so.
              TextButton.icon(
                icon: const Icon(Icons.stop_circle_outlined, size: 18),
                label: const Text('Stop tracking'),
                onPressed: () async {
                  final confirmed = await _confirmStopTracking(
                    context,
                    state.discreet,
                    state.relapses.isNotEmpty,
                  );
                  if (confirmed != true) return;
                  await ref.read(sobrietyProvider.notifier).clearDate();
                  if (context.mounted) Navigator.of(context).maybePop();
                },
              ),
            if (_showSupport) ...[
              const SizedBox(height: AppSpacing.sm),
              _SupportPanel(discreet: state.discreet),
            ],
            if (state.isTracking) ...[
              const SizedBox(height: AppSpacing.xs),
              _SlippedAffordance(onTap: _onSlipped),
            ],
          ],
        ),
      ),
    );
  }
}

/// Shame-free relapse history shown on the tracker editor: longest streak and
/// total count, plus the list of past events (date, note, lost days). In
/// discreet mode the ambient wording avoids the word "relapse". The list is
/// capped at [_maxHistoryTiles] so a long history cannot overflow the sheet;
/// an explicit control can erase all history.
class _HistorySection extends ConsumerWidget {
  final bool discreet;

  /// Maximum number of event rows rendered; older events stay stored but are
  /// not listed, keeping the sheet from overflowing.
  static const int _maxHistoryTiles = 8;

  const _HistorySection({required this.discreet});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(sobrietyProvider);
    final theme = Theme.of(context);
    final best = state.longestStreak;
    final total = state.totalRelapses;
    final shown = state.relapses.reversed.take(_maxHistoryTiles).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Divider(height: 1),
        const SizedBox(height: AppSpacing.md),
        Text(
          discreet ? 'History' : 'Your journey',
          style: theme.textTheme.titleSmall
              ?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          discreet
              ? 'Longest run: $best days · Restarts: $total'
              : 'Longest streak: $best days · Relapses: $total. '
                  'The journey continues today.',
          style: theme.textTheme.bodySmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: AppSpacing.sm),
        ...shown.map((r) {
          final label = DateFormat.yMMMMd().format(r.date);
          final lostDays = r.lostDays;
          String subtitle;
          if (discreet) {
            subtitle = lostDays > 0
                ? 'Day count restarted — $lostDays day run'
                : 'Day count restarted';
          } else if (r.note.isNotEmpty) {
            subtitle = lostDays > 0
                ? '${r.note} · $lostDays day run reset'
                : r.note;
          } else {
            subtitle = lostDays > 0
                ? '$lostDays day run reset'
                : 'Day count restarted';
          }
          return ListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            leading: const Icon(Icons.history, size: 18),
            title: Text(label),
            subtitle: Text(subtitle),
          );
        }),
        if (state.relapses.length > _maxHistoryTiles)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
              discreet
                  ? 'Older restarts are kept on this device.'
                  : 'Older history is kept privately on this device.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          ),
        const SizedBox(height: AppSpacing.xs),
        if (state.relapses.isNotEmpty)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              style: TextButton.styleFrom(
                foregroundColor: AppColors.error,
                visualDensity: VisualDensity.compact,
              ),
              icon: const Icon(Icons.delete_sweep_outlined, size: 16),
              label: Text(
                  discreet ? 'Erase restart history' : 'Erase relapse history'),
              onPressed: () async {
                final doErase = await _confirmErase(context, discreet);
                if (doErase != true) return;
                await ref.read(sobrietyProvider.notifier).clearRelapses();
              },
            ),
          )
        else if (state.bestStreakDays > 0)
          // History already erased but the preserved record remains: keep it
          // erasable too, so a full in-app wipe (or fixing a record inflated
          // by a mis-set date) is always possible.
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              style: TextButton.styleFrom(
                foregroundColor: AppColors.error,
                visualDensity: VisualDensity.compact,
              ),
              icon: const Icon(Icons.delete_sweep_outlined, size: 16),
              label: Text(discreet
                  ? 'Erase longest-run record'
                  : 'Erase longest-streak record'),
              onPressed: () async {
                final doErase = await _confirmEraseRecord(
                    context, discreet, state.bestStreakDays);
                if (doErase != true) return;
                await ref.read(sobrietyProvider.notifier).clearBestStreak();
              },
            ),
          ),
      ],
    );
  }
}

/// Asks before permanently deleting the preserved longest-streak record.
/// Returns true when the user confirms.
Future<bool?> _confirmEraseRecord(
  BuildContext context,
  bool discreet,
  int days,
) {
  return showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(discreet
          ? 'Erase longest-run record?'
          : 'Erase longest-streak record?'),
      content: Text(
        discreet
            ? 'This permanently deletes the $days-day longest-run record '
                'from this device. This cannot be undone. Your current day '
                'count is unchanged.'
            : 'This permanently deletes the $days-day longest-streak record '
                'from this device. This cannot be undone. Your current day '
                'count is unchanged.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          child: const Text('Cancel'),
        ),
        TextButton(
          style: TextButton.styleFrom(foregroundColor: AppColors.error),
          onPressed: () => Navigator.of(dialogContext).pop(true),
          child: const Text('Erase'),
        ),
      ],
    ),
  );
}

/// Asks before turning the day counter off. Makes explicit that history is
/// kept (the old flow looked like a data delete while silently retaining
/// notes) — but only claims history exists when it does, so a user with no
/// logged relapses isn't sent hunting for data the app doesn't hold.
/// Returns true when the user confirms.
Future<bool?> _confirmStopTracking(
  BuildContext context,
  bool discreet,
  bool hasHistory,
) {
  return showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Stop tracking?'),
      content: Text(
        !hasHistory
            ? 'The day counter turns off. You can start tracking again '
                'any time.'
            : discreet
                ? 'The day counter turns off. Your history and notes stay on '
                    'this device — you can erase them separately.'
                : 'The day counter turns off. Your relapse history and notes '
                    'stay on this device — you can erase them separately with '
                    '"Erase relapse history".',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          child: const Text('Cancel'),
        ),
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(true),
          child: const Text('Stop tracking'),
        ),
      ],
    ),
  );
}

/// Asks before permanently deleting all relapse history. Returns true when the
/// user confirms.
Future<bool?> _confirmErase(BuildContext context, bool discreet) {
  return showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(discreet ? 'Erase restart history?' : 'Erase relapse history?'),
      content: Text(
        discreet
            ? 'This permanently deletes every logged restart and any notes '
                'from this device. This cannot be undone. This does not '
                'change your current day count, and your longest-run record '
                'is kept.'
            : 'This permanently deletes every logged relapse and any notes '
                'from this device. This cannot be undone. This does not reset '
                'your current day count, and your longest-streak record is '
                'kept.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          child: const Text('Cancel'),
        ),
        TextButton(
          style: TextButton.styleFrom(foregroundColor: AppColors.error),
          onPressed: () => Navigator.of(dialogContext).pop(true),
          child: const Text('Erase'),
        ),
      ],
    ),
  );
}

/// Low-key "Slipped? Restart without losing your history" affordance on the
/// tracker editor. Kept off the always-visible day card so relapse logging
/// isn't advertised on the daily surface; full wording appears inside the
/// explicit confirm dialog. The caller supplies [onTap] so the sheet can run
/// its own confirmation flow.
class _SlippedAffordance extends ConsumerWidget {
  final VoidCallback onTap;

  const _SlippedAffordance({required this.onTap});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final discreet = ref.watch(sobrietyProvider).discreet;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.restart_alt, size: 20),
      title: Text(
        discreet ? 'Restart log' : 'Slipped? Restart without losing your history',
        style: Theme.of(context).textTheme.bodyMedium,
      ),
      subtitle: Text(
        discreet
            ? 'Resets the day count. Your history stays.'
            : "Resets today's count. Your history and longest streak are kept.",
      ),
      onTap: onTap,
    );
  }
}

/// Supportive confirmation shown inside the tracker sheet after a relapse is
/// logged — visible (unlike a snackbar behind the modal) and with a working
/// crisis link (unlike one tied to the dismissed dialog's context). Watches
/// the history so the "your history is kept" claim disappears if the user
/// erases their history while the panel is still showing.
class _SupportPanel extends ConsumerWidget {
  final bool discreet;

  const _SupportPanel({required this.discreet});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hasHistory = ref.watch(
      sobrietyProvider.select((s) => s.relapses.isNotEmpty),
    );
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: cs.secondaryContainer.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(AppSpacing.radius),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            discreet
                ? (hasHistory
                    ? 'Day count restarted. Your history stays.'
                    : 'Day count restarted.')
                : (hasHistory
                    ? "You're back. Today is day one again — your history "
                        'is kept.'
                    : "You're back. Today is day one again."),
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: AppSpacing.xs),
          TextButton.icon(
            style: TextButton.styleFrom(
              foregroundColor: cs.primary,
              padding: EdgeInsets.zero,
              visualDensity: VisualDensity.compact,
            ),
            onPressed: () => showAppSheet(context, const CrisisSheet()),
            icon: const Icon(Icons.support_agent, size: 18),
            label: const Text('Get support now'),
          ),
        ],
      ),
    );
  }
}

/// Shame-free "log a relapse" dialog: optional note + trigger, gentle confirm
/// that resets the count without losing history. Returns true when the user
/// confirmed (the caller then surfaces the supportive message + crisis link
/// inside the sheet, so it stays visible and reachable).
Future<bool> showRelapseLogDialog(
  BuildContext context,
  WidgetRef ref, {
  required bool discreet,
}) {
  return showDialog<bool>(
    context: context,
    builder: (dialogContext) => _RelapseLogDialog(discreet: discreet),
  ).then((v) => v ?? false);
}

class _RelapseLogDialog extends ConsumerStatefulWidget {
  final bool discreet;

  const _RelapseLogDialog({required this.discreet});

  @override
  ConsumerState<_RelapseLogDialog> createState() => _RelapseLogDialogState();
}

class _RelapseLogDialogState extends ConsumerState<_RelapseLogDialog> {
  final _note = TextEditingController();
  String _trigger = '';

  static const _triggers = [
    'Stress',
    'Social',
    'Craving',
    'Habit',
    'Celebration',
  ];

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _confirm() async {
    await ref
        .read(sobrietyProvider.notifier)
        .logRelapse(note: _note.text.trim(), trigger: _trigger);
    if (!mounted) return;
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: Text(widget.discreet ? 'Restart log' : 'Log a relapse'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.discreet
                  ? 'This restarts today\'s count. Your history stays.'
                  : 'This resets today\'s count. Your history and longest '
                      'streak are kept. Nothing is sent anywhere.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(
              controller: _note,
              maxLines: 2,
              decoration: const InputDecoration(
                isDense: true,
                labelText: 'Note (optional)',
                hintText: 'What happened? Only you ever see this.',
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Trigger (optional)',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.xs),
            Wrap(
              spacing: AppSpacing.xs,
              runSpacing: AppSpacing.xs,
              children: _triggers
                  .map(
                    (t) => ChoiceChip(
                      label: Text(t),
                      selected: _trigger == t,
                      onSelected: (sel) =>
                          setState(() => _trigger = sel ? t : ''),
                    ),
                  )
                  .toList(),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _confirm,
          child: Text(widget.discreet ? 'Restart' : 'Restart day count'),
        ),
      ],
    );
  }
}
