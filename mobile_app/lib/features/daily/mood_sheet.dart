import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:share_plus/share_plus.dart';

import 'package:sobriety_copilot_mobile/features/daily/inventory.dart'
    show dateIsoOf;
import 'package:sobriety_copilot_mobile/features/daily/mood_history.dart';
import 'package:sobriety_copilot_mobile/features/daily/mood_log.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Max journal length, enforced in the UI with a live counter (no silent
/// truncation on write).
const int kMoodJournalMaxChars = 5000;

/// Emoji shown beside each emotion label in the selector. Indexed by the
/// [kMoodEmotions] order.
const List<String> kMoodEmotionIcons = [
  '🙏', // Grateful
  '🕊️', // Peaceful
  '🌟', // Hopeful
  '😌', // Content
  '🌊', // Calm
  '😐', // Okay
  '🌀', // Restless
  '😰', // Anxious
  '😢', // Sad
  '😠', // Angry
  '🙁', // Ashamed
  '🫥', // Alone
  '💔', // Hopeless
];

/// Daily mood/emotion check-in ("How are you feeling right now?"). A curated
/// emotion selector with an optional free-text journal. One entry per day
/// (upsert). Purely on-device; sharing a single entry is explicit-only.
///
/// This is a morning/any-time surface (vs. the nightly evening review).
class MoodSheet extends ConsumerStatefulWidget {
  const MoodSheet({super.key});

  @override
  ConsumerState<MoodSheet> createState() => _MoodSheetState();
}

class _MoodSheetState extends ConsumerState<MoodSheet> {
  String? _label;
  int? _mood;
  late final TextEditingController _journal;

  @override
  void initState() {
    super.initState();
    final existing = ref.read(moodProvider.notifier).entryFor(DateTime.now());
    _label = existing?.label;
    _mood = existing?.mood;
    _journal = TextEditingController(text: existing?.journal ?? '');
  }

  @override
  void dispose() {
    _journal.dispose();
    super.dispose();
  }

  void _selectEmotion(String label) {
    setState(() {
      _label = label;
      _mood = kEmotionMood[label] ?? _mood;
    });
  }

  MoodEntry _buildEntry() {
    return MoodEntry(
      dateIso: dateIsoOf(DateTime.now()),
      mood: _mood ?? 3,
      label: _label ?? '',
      journal: _journal.text.trim(),
    );
  }

  Future<void> _save() async {
    final notifier = ref.read(moodProvider.notifier);
    final entry = _buildEntry();
    final isToday = entry.dateIso == dateIsoOf(DateTime.now());
    await notifier.upsert(entry);
    // TODO(fr5): recordCheckIn() — FR5 (streaks) wires the check-in record.
    if (isToday) {
      // FR5 hook: see TODO above.
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Mood saved.')),
      );
      Navigator.of(context).maybePop();
    }
  }

  void _share(MoodEntry entry) {
    SharePlus.instance.share(
      ShareParams(text: entry.toShareText(), subject: "How I'm feeling"),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final today = DateTime.now();
    final existing = ref.watch(moodProvider.notifier).entryFor(today);

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
                    const Icon(Icons.emoji_emotions_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('How are you feeling?',
                              style: theme.textTheme.titleLarge),
                          Text(
                            DateFormat.yMMMMd().format(today),
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    if (existing != null)
                      IconButton(
                        tooltip: 'Share journal entry',
                        icon: const Icon(Icons.ios_share),
                        onPressed: () => _share(existing),
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
                    Text(
                      'A quick check-in — private, on your device. '
                      "If you've already checked in today we'll update it.",
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontStyle: FontStyle.italic,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    if (existing != null)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Chip(
                          avatar: const Icon(Icons.check_circle_outline,
                              size: 16, color: AppColors.accent),
                          label: Text(existing.label.isNotEmpty
                              ? '${existing.label} · mood ${existing.mood}/5'
                              : 'mood ${existing.mood}/5'),
                          visualDensity: VisualDensity.compact,
                        ),
                      ),
                    const SectionHeader('Pick how you feel'),
                    const SizedBox(height: AppSpacing.xs),
                    Wrap(
                      spacing: AppSpacing.xs,
                      runSpacing: AppSpacing.xs,
                      children: [
                        for (var i = 0; i < kMoodEmotions.length; i++)
                          ChoiceChip(
                            label: Text(
                              '${kMoodEmotionIcons[i]} ${kMoodEmotions[i]}',
                            ),
                            selected: _label == kMoodEmotions[i],
                            onSelected: (_) =>
                                _selectEmotion(kMoodEmotions[i]),
                          ),
                      ],
                    ),
                    if (_mood != null) ...[
                      const SizedBox(height: AppSpacing.sm),
                      Text(
                        'Mood $_mood/5',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: moodColor(context, _mood!),
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                    const SizedBox(height: AppSpacing.lg),
                    const SectionHeader('Journal (optional)'),
                    const SizedBox(height: AppSpacing.xs),
                    TextField(
                      controller: _journal,
                      maxLines: null,
                      maxLength: kMoodJournalMaxChars,
                      decoration: const InputDecoration(
                        isDense: true,
                        hintText: 'A few honest sentences…',
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    FilledButton.icon(
                      icon: const Icon(Icons.check),
                      label: const Text('Save check-in'),
                      onPressed: _save,
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    const Divider(height: 1),
                    const SizedBox(height: AppSpacing.sm),
                    const MoodHistory(),
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
