import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:share_plus/share_plus.dart';

import 'package:sobriety_copilot_mobile/features/daily/inventory.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Evening review (10th/11th-step nightly inventory): the Big Book's
/// questions as toggles, follow-up notes on flagged answers, a reflection
/// prompt, and a gratitude list. Local-only; share is explicit (sponsor
/// export via the OS share sheet).
class InventorySheet extends ConsumerStatefulWidget {
  const InventorySheet({super.key});

  @override
  ConsumerState<InventorySheet> createState() => _InventorySheetState();
}

class _InventorySheetState extends ConsumerState<InventorySheet> {
  late Map<String, bool> _answers;
  late Map<String, TextEditingController> _noteControllers;
  late TextEditingController _reflection;
  late TextEditingController _gratitudeInput;
  late List<String> _gratitude;
  bool _dirty = false;

  @override
  void initState() {
    super.initState();
    final existing =
        ref.read(inventoryProvider.notifier).entryFor(DateTime.now());
    _answers = {
      for (final q in kInventoryQuestions)
        // Untouched default is the favorable answer for each question.
        q.id: existing?.answers[q.id] ?? !q.unfavorableWhenYes,
    };
    _noteControllers = {
      for (final q in kInventoryQuestions)
        q.id: TextEditingController(text: existing?.notes[q.id] ?? ''),
    };
    _reflection = TextEditingController(text: existing?.reflection ?? '');
    _gratitudeInput = TextEditingController();
    _gratitude = List.of(existing?.gratitude ?? const []);
  }

  @override
  void dispose() {
    for (final c in _noteControllers.values) {
      c.dispose();
    }
    _reflection.dispose();
    _gratitudeInput.dispose();
    super.dispose();
  }

  InventoryEntry _buildEntry() {
    return InventoryEntry(
      dateIso: dateIsoOf(DateTime.now()),
      answers: Map.of(_answers),
      notes: {
        for (final e in _noteControllers.entries)
          if (e.value.text.trim().isNotEmpty) e.key: e.value.text.trim(),
      },
      reflection: _reflection.text.trim(),
      gratitude: List.of(_gratitude),
    );
  }

  Future<void> _save() async {
    await ref.read(inventoryProvider.notifier).save(_buildEntry());
    _dirty = false;
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Saved — good night.')),
      );
      Navigator.of(context).maybePop();
    }
  }

  void _addGratitude() {
    final text = _gratitudeInput.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _gratitude.add(text);
      _gratitudeInput.clear();
      _dirty = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final entries = ref.watch(inventoryProvider);
    final streak = ref.read(inventoryProvider.notifier).streak;
    final today = DateTime.now();

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
                    const Icon(Icons.nightlight_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Evening review',
                              style: theme.textTheme.titleLarge),
                          Text(
                            DateFormat.yMMMMd().format(today),
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    if (streak > 0)
                      Chip(
                        avatar: const Icon(Icons.local_fire_department,
                            size: 16, color: AppColors.gold),
                        label: Text('$streak-day streak'),
                        visualDensity: VisualDensity.compact,
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
                      '"When we retire at night, we constructively review our '
                      'day." Answer honestly — this stays on your device.',
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontStyle: FontStyle.italic,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    for (final q in kInventoryQuestions) ...[
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        title: Text(q.text),
                        value: _answers[q.id] ?? false,
                        onChanged: (v) => setState(() {
                          _answers[q.id] = v;
                          _dirty = true;
                        }),
                      ),
                      if ((_answers[q.id] ?? false) == q.unfavorableWhenYes)
                        Padding(
                          padding: const EdgeInsets.only(
                            left: AppSpacing.md,
                            bottom: AppSpacing.sm,
                          ),
                          child: TextField(
                            controller: _noteControllers[q.id],
                            maxLines: null,
                            onChanged: (_) => _dirty = true,
                            decoration: const InputDecoration(
                              isDense: true,
                              hintText: 'What happened? (optional)',
                            ),
                          ),
                        ),
                    ],
                    const SizedBox(height: AppSpacing.md),
                    const SectionHeader(kInventoryFreeTextPrompt),
                    const SizedBox(height: AppSpacing.xs),
                    TextField(
                      controller: _reflection,
                      maxLines: null,
                      onChanged: (_) => _dirty = true,
                      decoration: const InputDecoration(
                        isDense: true,
                        hintText: 'A sentence or two…',
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    const SectionHeader('Grateful for'),
                    const SizedBox(height: AppSpacing.xs),
                    if (_gratitude.isNotEmpty)
                      Wrap(
                        spacing: AppSpacing.xs,
                        runSpacing: AppSpacing.xs,
                        children: [
                          for (var i = 0; i < _gratitude.length; i++)
                            Chip(
                              label: Text(_gratitude[i]),
                              onDeleted: () => setState(() {
                                _gratitude.removeAt(i);
                                _dirty = true;
                              }),
                            ),
                        ],
                      ),
                    TextField(
                      controller: _gratitudeInput,
                      onSubmitted: (_) => _addGratitude(),
                      decoration: InputDecoration(
                        isDense: true,
                        hintText: 'Add one thing…',
                        suffixIcon: IconButton(
                          icon: const Icon(Icons.add),
                          onPressed: _addGratitude,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    Row(
                      children: [
                        Expanded(
                          child: FilledButton.icon(
                            icon: const Icon(Icons.check),
                            label: const Text('Save review'),
                            onPressed: _save,
                          ),
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        IconButton(
                          tooltip: 'Share with your sponsor',
                          icon: const Icon(Icons.ios_share),
                          onPressed: () {
                            SharePlus.instance.share(
                              ShareParams(text: _buildEntry().toShareText()),
                            );
                          },
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    _HistoryStrip(entries: entries),
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

/// Last 14 days as filled/empty dots — lightweight history without a
/// full calendar.
class _HistoryStrip extends StatelessWidget {
  final Map<String, InventoryEntry> entries;
  const _HistoryStrip({required this.entries});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final today = DateTime.now();
    final days = [
      for (var i = 13; i >= 0; i--)
        today.subtract(Duration(days: i)),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader('Last two weeks'),
        const SizedBox(height: AppSpacing.sm),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            for (final d in days)
              Column(
                children: [
                  Container(
                    width: 14,
                    height: 14,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: entries.containsKey(dateIsoOf(d))
                          ? AppColors.accent
                          : theme.colorScheme.surfaceContainerHighest,
                      border: Border.all(
                        color: theme.colorScheme.outlineVariant,
                      ),
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    DateFormat.E().format(d).substring(0, 1),
                    style: theme.textTheme.bodySmall
                        ?.copyWith(fontSize: 9),
                  ),
                ],
              ),
          ],
        ),
      ],
    );
  }
}
