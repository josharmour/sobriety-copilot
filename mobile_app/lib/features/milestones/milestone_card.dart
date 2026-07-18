import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import 'package:sobriety_copilot_mobile/config/capabilities.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

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
          ],
        ),
      ),
    );
  }
}
