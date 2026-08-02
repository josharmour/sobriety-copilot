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

    final decoration = BoxDecoration(
      color: Colors.black.withAlpha(120),
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      border: Border.all(color: Colors.white24),
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
                  const Icon(Icons.emoji_events_outlined,
                      color: Colors.white70, size: 20),
                  const SizedBox(width: AppSpacing.sm),
                  Text(
                    'Track your sober time',
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: Colors.white70),
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
                    border: Border.all(color: Colors.white38),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  'Day $days',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: Colors.white70,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(width: AppSpacing.xs),
                const Icon(Icons.edit_outlined,
                    color: Colors.white38, size: 14),
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
                        border: Border.all(color: Colors.white38),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        headline,
                        style: theme.textTheme.titleLarge?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const Icon(Icons.edit_outlined,
                        color: Colors.white38, size: 16),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  subtitle,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: Colors.white70),
                ),
                const SizedBox(height: AppSpacing.sm),
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: state.milestoneProgress,
                    minHeight: 5,
                    backgroundColor: Colors.white24,
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

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(sobrietyProvider);
    final theme = Theme.of(context);
    final dateLabel = state.sobrietyDate == null
        ? 'Not set'
        : DateFormat.yMMMMd().format(state.sobrietyDate!);

    return SafeArea(
      top: false,
      child: Padding(
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
            if (state.isTracking && state.relapses.isNotEmpty) ...[
              _HistorySection(discreet: state.discreet),
              const SizedBox(height: AppSpacing.md),
            ],
            if (state.isTracking)
              TextButton.icon(
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.error,
                ),
                icon: const Icon(Icons.delete_outline, size: 18),
                label: const Text('Stop tracking'),
                onPressed: () async {
                  await ref.read(sobrietyProvider.notifier).clearDate();
                  if (context.mounted) Navigator.of(context).maybePop();
                },
              ),
            if (state.isTracking) ...[
              const SizedBox(height: AppSpacing.xs),
              _SlippedAffordance(discreet: state.discreet),
            ],
          ],
        ),
      ),
    );
  }
}

/// Shame-free relapse history shown on the tracker editor: longest streak and
/// total count, plus the list of past events (date, note, lost days). In
/// discreet mode the ambient wording avoids the word \"relapse\".
class _HistorySection extends ConsumerWidget {
  final bool discreet;

  const _HistorySection({required this.discreet});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(sobrietyProvider);
    final theme = Theme.of(context);
    final best = state.longestStreak;
    final total = state.totalRelapses;

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
              : 'Longest streak: $best days · Relapses: $total — each one '
                  'taught you something. The journey continues today.',
          style: theme.textTheme.bodySmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: AppSpacing.sm),
        ...state.relapses.reversed.map((r) {
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
      ],
    );
  }
}

/// Low-key \"Slipped? Restart without losing your history\" affordance on the
/// tracker editor. Kept off the always-visible day card so relapse logging
/// isn't advertised on the daily surface; full wording appears inside the
/// explicit confirm dialog. In discreet mode the ambient wording avoids the
/// word \"relapse\".
class _SlippedAffordance extends ConsumerWidget {
  final bool discreet;

  const _SlippedAffordance({required this.discreet});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
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
            : 'Resets today\'s count. Your history and longest streak are kept.',
      ),
      onTap: () => showRelapseLogDialog(context, ref, discreet: discreet),
    );
  }
}

/// Shame-free \"log a relapse\" dialog: optional note + trigger, gentle
/// confirm that resets the count without losing history, then a supportive
/// snackbar plus a link to the crisis/support sheet.
Future<void> showRelapseLogDialog(
  BuildContext context,
  WidgetRef ref, {
  required bool discreet,
}) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) => _RelapseLogDialog(discreet: discreet),
  );
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
    Navigator.of(context).pop();
    final messenger = ScaffoldMessenger.of(context);
    final support = Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(widget.discreet
            ? 'Day count restarted. Your history stays.'
            : 'You\'re back. Today is day one again — your history is kept.'),
        TextButton(
          onPressed: () {
            messenger.hideCurrentSnackBar();
            showAppSheet(context, const CrisisSheet());
          },
          child: const Text('Get support now'),
        ),
      ],
    );
    messenger.showSnackBar(
      SnackBar(
        content: support,
        duration: const Duration(seconds: 6),
      ),
    );
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
