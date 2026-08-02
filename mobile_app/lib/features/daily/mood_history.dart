import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import 'package:sobriety_copilot_mobile/features/daily/inventory.dart'
    show dateIsoOf;
import 'package:sobriety_copilot_mobile/features/daily/mood_log.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// 30-day mood trend: a no-dependency grid of colored squares, each colored
/// by mood value using the app palette. Tapping a day expands its label +
/// journal inline (same sheet, no new route). Empty days render dim.
class MoodHistory extends ConsumerStatefulWidget {
  const MoodHistory({super.key});

  @override
  ConsumerState<MoodHistory> createState() => _MoodHistoryState();
}

class _MoodHistoryState extends ConsumerState<MoodHistory> {
  /// Currently expanded (tapped) dateIso, or null.
  String? _expanded;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final entries = ref.watch(moodProvider);
    final today = DateTime.now();
    final days = [
      for (var i = 29; i >= 0; i--) today.subtract(Duration(days: i)),
    ];
    final byIso = {for (final e in entries) e.dateIso: e};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader('Last 30 days'),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Your emotional pattern — kept only on this device.',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        Wrap(
          spacing: AppSpacing.xs,
          runSpacing: AppSpacing.xs,
          children: [
            for (final d in days)
              _MoodDayTile(
                date: d,
                isToday: dateIsoOf(d) == dateIsoOf(today),
                entry: byIso[dateIsoOf(d)],
                expanded: _expanded == dateIsoOf(d),
                onTap: () => setState(() {
                  if (byIso[dateIsoOf(d)] == null) return;
                  _expanded =
                      _expanded == dateIsoOf(d) ? null : dateIsoOf(d);
                }),
              ),
          ],
        ),
        if (_expanded != null && byIso[_expanded] != null) ...[
          const SizedBox(height: AppSpacing.sm),
          _MoodDayDetail(entry: byIso[_expanded]!),
        ],
      ],
    );
  }
}

/// Colors a mood value using the app palette (not raw green/red) — a smooth
/// ramp from the brand navy (low) through gold (neutral) to the cyan accent
/// (high). Mirrors how milestone/token colors are pulled from the palette.
Color moodColor(BuildContext context, int mood) {
  final isDark = Theme.of(context).brightness == Brightness.dark;
  return switch (mood) {
    5 => AppColors.accent,
    4 => const Color(0xFF7BC6D9),
    3 => AppColors.gold,
    2 => const Color(0xFFCA8A5C),
    1 => AppColors.brand,
    _ => isDark ? AppColors.darkText : AppColors.lightText,
  };
}

/// One day's square in the trend grid.
class _MoodDayTile extends StatelessWidget {
  final DateTime date;
  final bool isToday;
  final MoodEntry? entry;
  final bool expanded;
  final VoidCallback onTap;

  const _MoodDayTile({
    required this.date,
    required this.isToday,
    required this.entry,
    required this.expanded,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dim = theme.colorScheme.surfaceContainerHighest;
    final fill = entry == null ? dim : moodColor(context, entry!.mood);
    final border = isToday
        ? Border.all(color: AppColors.accent, width: 2)
        : Border.all(color: theme.colorScheme.outlineVariant);
    final dayNum = date.day.toString();

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppSpacing.xs),
      child: Container(
        width: 36,
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: fill,
          borderRadius: BorderRadius.circular(AppSpacing.xs),
          border: border,
        ),
        child: Text(
          dayNum,
          style: theme.textTheme.bodySmall?.copyWith(
            color: entry == null
                ? theme.colorScheme.onSurfaceVariant
                : Colors.white,
            fontWeight: isToday ? FontWeight.w800 : FontWeight.w500,
            fontSize: 11,
          ),
        ),
      ),
    );
  }
}

/// Expanded detail for a tapped day: label, mood, and journal text.
class _MoodDayDetail extends StatelessWidget {
  final MoodEntry entry;
  const _MoodDayDetail({required this.entry});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final date = DateTime.tryParse(entry.dateIso);
    final dateLabel = date == null
        ? entry.dateIso
        : DateFormat.yMMMd().format(date);
    return Material(
      color: AppColors.accentSoft.withValues(alpha: 0.5),
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '$dateLabel · ${entry.label.isNotEmpty ? entry.label : 'Mood ${entry.mood}/5'}',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                Text(
                  '${entry.mood}/5',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: moodColor(context, entry.mood),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            if (entry.journal.trim().isNotEmpty) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(entry.journal.trim(), style: theme.textTheme.bodyMedium),
            ],
          ],
        ),
      ),
    );
  }
}
