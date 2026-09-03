import 'dart:math' as math;

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
    // Calendar-date arithmetic (not Duration) so the 30-day grid is
    // DST-safe: near a transition, subtracting exact 24h periods would
    // duplicate one calendar day and drop another.
    final days = [
      for (var i = 29; i >= 0; i--)
        DateTime(today.year, today.month, today.day - i),
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
/// ramp from a deep navy (low) through gold (neutral) to the cyan accent
/// (high). Dark-mode aware: on a dark surface the low-mood fill lifts off the
/// navy background instead of vanishing into it. Mirrors how milestone/token
/// colors are pulled from the palette.
Color moodColor(BuildContext context, int mood) {
  final isDark = Theme.of(context).brightness == Brightness.dark;
  return switch (mood) {
    5 => AppColors.accent,
    4 => const Color(0xFF7BC6D9),
    3 => AppColors.gold,
    2 => const Color(0xFFCA8A5C),
    // Dark: a visible muted plum so mood-1 days never read as empty.
    1 => isDark ? const Color(0xFF6D5A88) : AppColors.brand,
    _ => isDark ? AppColors.darkText : AppColors.lightText,
  };
}

/// Returns a foreground color (black or white) that reads on [background],
/// chosen by WCAG relative luminance. Used for the day numbers and mood text
/// on the colored tiles, which span light and dark fills.
Color readableOn(Color background) {
  // WCAG relative luminance. Color.r/g/b are already normalized 0–1 doubles.
  double chan(double s) =>
      s <= 0.03928 ? s / 12.92 : math.pow((s + 0.055) / 1.055, 2.4).toDouble();

  final lum = 0.2126 * chan(background.r) +
      0.7152 * chan(background.g) +
      0.0722 * chan(background.b);
  // 0.179 is the luminance where black and white text have equal WCAG
  // contrast — above it dark text always contrasts better (a higher cutoff
  // would put failing white text on mid-luminance fills like the mood-2 tan).
  return lum > 0.179 ? Colors.black87 : Colors.white;
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
    // Accessible foreground that contrasts with the fill (the mid-ramp golds
    // and cyans are too light for white text).
    final fg = entry == null
        ? theme.colorScheme.onSurfaceVariant
        : readableOn(fill);
    // Screen-reader label describing the day (empty days are not clickable).
    final month = DateFormat.MMM().format(date);
    final e = entry;
    final semantic = e == null
        ? '$month ${date.day}, no check-in'
        : '$month ${date.day}, ${e.label.isEmpty ? 'mood ${e.mood} of 5' : e.label}, '
            'mood ${e.mood} of 5';

    return Semantics(
      button: true,
      enabled: entry != null,
      label: semantic,
      child: InkWell(
        onTap: entry == null ? null : onTap,
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
              color: fg,
              fontWeight:
                  isToday ? FontWeight.w800 : FontWeight.w600,
              fontSize: 11,
            ),
          ),
        ),
      ),
    );
  }
}

/// Expanded detail for a tapped day: label, mood, and journal text, with an
/// option to permanently delete that day's entry.
class _MoodDayDetail extends ConsumerWidget {
  final MoodEntry entry;
  const _MoodDayDetail({required this.entry});

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
    final doDelete = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete this entry?'),
        content: const Text(
            'This permanently removes this mood and journal text from this '
            'device. This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            style: TextButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
            ),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (doDelete == true) {
      // A malformed dateIso must be a no-op, never a fallback that would
      // silently delete today's entry instead.
      final date = DateTime.tryParse(entry.dateIso);
      if (date == null) return;
      await ref.read(moodProvider.notifier).delete(date);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final date = DateTime.tryParse(entry.dateIso);
    final dateLabel = date == null
        ? entry.dateIso
        : DateFormat.yMMMd().format(date);
    final moodFg = moodColor(context, entry.mood);
    return Material(
      color: AppColors.highlightBg(
        theme.brightness == Brightness.dark,
      ),
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
                // Mood shown as a color swatch + full-contrast text (the ramp
                // color alone fails WCAG as a text color on the card fill).
                Container(
                  width: 10,
                  height: 10,
                  margin: const EdgeInsets.only(right: AppSpacing.xs),
                  decoration: BoxDecoration(
                    color: moodFg,
                    shape: BoxShape.circle,
                  ),
                ),
                Text(
                  '${entry.mood}/5',
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            if (entry.journal.trim().isNotEmpty) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(entry.journal.trim(), style: theme.textTheme.bodyMedium),
            ],
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                style: TextButton.styleFrom(
                  foregroundColor: theme.colorScheme.error,
                  visualDensity: VisualDensity.compact,
                  padding: EdgeInsets.zero,
                ),
                onPressed: () => _confirmDelete(context, ref),
                icon: const Icon(Icons.delete_outline, size: 16),
                label: const Text('Delete entry'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
