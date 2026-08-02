import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/features/daily/daily_readings.dart';
import 'package:sobriety_copilot_mobile/features/daily/inventory.dart';
import 'package:sobriety_copilot_mobile/features/daily/inventory_sheet.dart';
import 'package:sobriety_copilot_mobile/features/daily/reminders.dart';
import 'package:sobriety_copilot_mobile/features/meditation/meditation_sheet.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// "Today" — the daily-practice surface: today's reading, the Big Book
/// morning practice, the evening check-in entry point, reminders, and
/// link-outs to the official copyrighted daily readers.
class TodaySheet extends ConsumerWidget {
  const TodaySheet({super.key});

  Future<void> _open(String url) async {
    final uri = Uri.parse(url);
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final readings = ref.watch(dailyReadingsProvider);
    final inventory = ref.watch(inventoryProvider);
    final streak = ref.read(inventoryProvider.notifier).streak;
    final now = DateTime.now();
    final doneToday = inventory.containsKey(dateIsoOf(now));

    return SafeArea(
      top: false,
      child: DraggableScrollableSheet(
        initialChildSize: 0.9,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) {
          return Column(
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
                    const Icon(Icons.wb_twilight_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Today', style: theme.textTheme.titleLarge),
                          Text(
                            DateFormat.yMMMMEEEEd().format(now),
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.check),
                      tooltip: 'Done',
                      onPressed: () => Navigator.of(context).maybePop(),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView(
                  controller: scrollController,
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    AppSpacing.md,
                    AppSpacing.lg,
                    AppSpacing.xxl,
                  ),
                  children: [
                    readings.when(
                      loading: () => const Padding(
                        padding: EdgeInsets.all(AppSpacing.xl),
                        child: Center(child: CircularProgressIndicator()),
                      ),
                      error: (_, __) => const SizedBox.shrink(),
                      data: (bundle) {
                        final reading = bundle.forDate(now);
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Card(
                              child: Padding(
                                padding: const EdgeInsets.all(AppSpacing.lg),
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Expanded(
                                          child: Text(
                                            reading.title,
                                            style: theme.textTheme.titleLarge
                                                ?.copyWith(
                                              fontWeight: FontWeight.w700,
                                            ),
                                          ),
                                        ),
                                        IconButton(
                                          visualDensity:
                                              VisualDensity.compact,
                                          tooltip: 'Share',
                                          icon: const Icon(Icons.ios_share,
                                              size: 18),
                                          onPressed: () =>
                                              SharePlus.instance.share(
                                            ShareParams(
                                              text:
                                                  '${reading.title}\n\n${reading.body}\n\n— ${reading.source}',
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: AppSpacing.sm),
                                    Text(
                                      reading.body,
                                      style: theme.textTheme.bodyMedium,
                                    ),
                                    const SizedBox(height: AppSpacing.sm),
                                    Text(
                                      '— ${reading.source}',
                                      style: theme.textTheme.bodySmall
                                          ?.copyWith(
                                        fontStyle: FontStyle.italic,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                            const SizedBox(height: AppSpacing.md),
                            _PracticeTile(
                              icon: Icons.wb_sunny_outlined,
                              reading: bundle.morningPractice,
                            ),
                            _PracticeTile(
                              icon: Icons.bedtime_outlined,
                              reading: bundle.eveningPractice,
                            ),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: AppSpacing.md),
                    Card(
                      child: ListTile(
                        leading: Icon(
                          doneToday
                              ? Icons.task_alt
                              : Icons.nightlight_outlined,
                          color: doneToday ? AppColors.accent : null,
                        ),
                        title: Text(
                          doneToday
                              ? 'Evening review — done'
                              : 'Evening review',
                        ),
                        subtitle: Text(
                          streak > 0
                              ? '$streak-day streak · tap to view or edit'
                              : 'A few honest minutes before bed',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => showAppSheet(
                          context,
                          const InventorySheet(),
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.self_improvement_outlined),
                        title: const Text('Meditation'),
                        subtitle: const Text(
                          'Guided breathing & grounding sessions',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => showAppSheet(
                          context,
                          const MeditationSheet(),
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    if (remindersSupported) ...[
                      const SectionHeader('Reminders'),
                      const _ReminderTiles(),
                      const SizedBox(height: AppSpacing.xl),
                    ],
                    const SectionHeader('Official daily readers'),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      'Daily Reflections and Just for Today are published by '
                      'A.A. World Services and N.A. World Services — read '
                      "today's page on their sites.",
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.open_in_new, size: 20),
                      title: const Text('Daily Reflections (aa.org)'),
                      onTap: () =>
                          _open('https://www.aa.org/daily-reflections'),
                    ),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.open_in_new, size: 20),
                      title: const Text('Just for Today (na.org)'),
                      onTap: () => _open('https://na.org/daily-meditations/'),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _PracticeTile extends StatelessWidget {
  final IconData icon;
  final DailyReading reading;
  const _PracticeTile({required this.icon, required this.reading});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Theme(
      data: theme.copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: AppSpacing.md),
        leading: Icon(icon, size: 20),
        title: Text(reading.title),
        children: [
          Text(reading.body, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.xs),
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              '— ${reading.source}',
              style: theme.textTheme.bodySmall
                  ?.copyWith(fontStyle: FontStyle.italic),
            ),
          ),
        ],
      ),
    );
  }
}

/// Morning/evening reminder switches with time pickers. Enabling requests
/// the notification permission in context (Android 13+).
class _ReminderTiles extends ConsumerWidget {
  const _ReminderTiles();

  Future<void> _pickTime(
    BuildContext context,
    WidgetRef ref, {
    required bool morning,
  }) async {
    final s = ref.read(reminderProvider);
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(
        hour: morning ? s.morningHour : s.eveningHour,
        minute: morning ? s.morningMinute : s.eveningMinute,
      ),
    );
    if (picked == null) return;
    final next = morning
        ? s.copyWith(morningHour: picked.hour, morningMinute: picked.minute)
        : s.copyWith(eveningHour: picked.hour, eveningMinute: picked.minute);
    await ref.read(reminderProvider.notifier).apply(next);
  }

  Future<void> _toggle(
    BuildContext context,
    WidgetRef ref,
    bool value, {
    required bool morning,
  }) async {
    final s = ref.read(reminderProvider);
    final next = morning
        ? s.copyWith(morningEnabled: value)
        : s.copyWith(eveningEnabled: value);
    final ok = await ref.read(reminderProvider.notifier).apply(next);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Notifications are turned off for this app in system settings.',
          ),
        ),
      );
    }
  }

  String _fmt(BuildContext context, int hour, int minute) =>
      TimeOfDay(hour: hour, minute: minute).format(context);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(reminderProvider);
    return Column(
      children: [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          dense: true,
          value: s.morningEnabled,
          title: const Text('Morning reading'),
          subtitle: GestureDetector(
            onTap: s.morningEnabled
                ? () => _pickTime(context, ref, morning: true)
                : null,
            child: Text(
              'Daily at ${_fmt(context, s.morningHour, s.morningMinute)}'
              '${s.morningEnabled ? ' · tap to change' : ''}',
            ),
          ),
          onChanged: (v) => _toggle(context, ref, v, morning: true),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          dense: true,
          value: s.eveningEnabled,
          title: const Text('Evening check-in'),
          subtitle: GestureDetector(
            onTap: s.eveningEnabled
                ? () => _pickTime(context, ref, morning: false)
                : null,
            child: Text(
              'Daily at ${_fmt(context, s.eveningHour, s.eveningMinute)}'
              '${s.eveningEnabled ? ' · tap to change' : ''}',
            ),
          ),
          onChanged: (v) => _toggle(context, ref, v, morning: false),
        ),
      ],
    );
  }
}
