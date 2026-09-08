// FR11 Wave C — MemorySheet: the on-device personal-memory manager.
//
// Mirrors the style of sheets/settings_sheet.dart: SafeArea(top:false) inside
// a DraggableScrollableSheet (showAppSheet-compatible), SectionHeader
// dividers, theme tokens, ListTile rows, HapticFeedback.selectionClick on
// every action, simple confirm dialogs. All mutations funnel through
// personalMemoryProvider methods; the toggle is the only other provider
// touched (memoryEnabledProvider).
//
// Privacy posture (matches FR11): memory is stored only on this device and
// travels ONLY inside the prompt (client_context / "About this person").
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/personal_memory/memory_snapshot.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Relative-ago caption for a fact/thread timestamp, minute resolution.
String agoFor(DateTime d) {
  final diff = DateTime.now().difference(d);
  if (diff.inMinutes < 1) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  if (diff.inDays < 30) return '${diff.inDays}d ago';
  return '${(diff.inDays / 30).truncate()}mo ago';
}

/// FR11.1 'Remember this': shared single-field edit dialog, mirroring the
/// MemorySheet `_prompt` visual language (AlertDialog + TextField + Cancel /
/// FilledButton Save) but with the memory-specific helper caption and a
/// Save that stays disabled while the text is blank/whitespace.
///
/// Returns the trimmed text on Save, null on Cancel/dismiss. The CALLER owns
/// all memory mutations — the dialog only gathers and validates text.
/// FR11.2 "Remember this" edit dialog. [suggester], when provided, runs
/// concurrently with the dialog open: while it works the field shows a
/// "Reading the conversation…" hint with a spinner; when it lands the field
/// is prefilled with the proposed fact (skipping null/empty suggestions).
/// The user can edit the suggestion freely or type from scratch either way.
Future<String?> promptRememberFact(
  BuildContext context, {
  required String prefilled,
  Future<String?> Function()? suggester,
}) {
  final controller = TextEditingController(text: prefilled);
  bool saveEnabled = prefilled.trim().isNotEmpty;
  bool suggesting = suggester != null;
  return showDialog<String>(
    context: context,
    builder:
        (dialogContext) => StatefulBuilder(
          builder: (dialogContext, setDialogState) {
            if (suggesting) {
              () async {
                String? suggestion;
                try {
                  suggestion = await suggester!();
                } catch (_) {
                  suggestion = null; // suggestion is best-effort only
                }
                if (!dialogContext.mounted) return;
                setDialogState(() {
                  suggesting = false;
                  if (suggestion != null &&
                      suggestion.trim().isNotEmpty &&
                      controller.text.trim().isEmpty) {
                    controller.text = suggestion.trim();
                    saveEnabled = true;
                  }
                });
              }();
            }
            return AlertDialog(
              title: const Text('Remember this'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: controller,
                    autofocus: true,
                    maxLines: 3,
                    minLines: 1,
                    onChanged: (v) {
                      final enabled = v.trim().isNotEmpty;
                      if (enabled != saveEnabled) {
                        setDialogState(() => saveEnabled = enabled);
                      }
                    },
                    onSubmitted:
                        (v) => Navigator.of(dialogContext).pop(v.trim()),
                    decoration: InputDecoration(
                      labelText: 'What should Copilot remember?',
                      hintText: suggesting ? 'Reading the conversation…' : null,
                      suffixIcon: suggesting
                          ? const Padding(
                              padding: EdgeInsets.all(12),
                              child: SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ),
                            )
                          : null,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    suggesting
                        ? 'Copilot is reading this conversation for something '
                            'worth remembering. You can also type it yourself.'
                        : 'Saved on this device. Copilot will use it as context '
                            'in future chats.',
                    style: Theme.of(
                      dialogContext,
                    ).textTheme.bodySmall?.copyWith(
                      color:
                          Theme.of(dialogContext).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(null),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed:
                      saveEnabled
                          ? () => Navigator.of(
                            dialogContext,
                          ).pop(controller.text.trim())
                          : null,
                  child: const Text('Save'),
                ),
              ],
            );
          },
        ),
  );
}

/// FR11 — the personal-memory management bottom sheet.
class MemorySheet extends ConsumerWidget {
  const MemorySheet({super.key});

  // ── Shared dialog helper for a single-field edit ──────────────────────────
  static Future<String?> _prompt(
    BuildContext context, {
    required String title,
    required String label,
    String initial = '',
  }) async {
    final controller = TextEditingController(text: initial);
    try {
      return await showDialog<String>(
        context: context,
        builder:
            (dialogContext) => AlertDialog(
              title: Text(title),
              content: TextField(
                controller: controller,
                autofocus: true,
                decoration: InputDecoration(labelText: label),
                onSubmitted: (v) => Navigator.of(dialogContext).pop(v.trim()),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(null),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed:
                      () => Navigator.of(
                        dialogContext,
                      ).pop(controller.text.trim()),
                  child: const Text('Save'),
                ),
              ],
            ),
      );
    } finally {
      controller.dispose();
    }
  }

  Future<void> _confirm(
    BuildContext context, {
    required String title,
    required String body,
    required Future<void> Function() onConfirm,
  }) {
    return showDialog<void>(
      context: context,
      builder:
          (dialogContext) => AlertDialog(
            title: Text(title),
            content: Text(body),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: () {
                  Navigator.of(dialogContext).pop();
                  onConfirm();
                },
                child: const Text('Confirm'),
              ),
            ],
          ),
    );
  }

  /// Resume flow: pop the sheet AND seed a NEW chat that carries the thread.
  void _resumeThread(BuildContext sheetContext, WidgetRef ref, MemoryThread t) {
    HapticFeedback.selectionClick();
    final notifier = ref.read(chatNotifierProvider.notifier);
    notifier.startNew();
    notifier.resumeThread(t);
    // Fire and forget: the notifier folds the SSE stream into its own state.
    // Never awaited from inside a modal pop (`pop` returns immediately).
    ref
        .read(chatNotifierProvider.notifier)
        .sendMessage(
          resumePromptFor(
            ThreadRef(
              title: t.title,
              lastDetail: t.lastDetail,
              updatedAt: t.updatedAt,
              resolved: t.resolved,
            ),
          ),
        );
    Navigator.of(sheetContext).pop();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memory = ref.watch(personalMemoryProvider);
    final memoryEnabled = ref.watch(memoryEnabledProvider);
    final memoryNotifier = ref.read(personalMemoryProvider.notifier);
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    final openThreads =
        memory.threads.where((t) => !t.resolved).toList()
          ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    final resolvedThreads =
        memory.threads.where((t) => t.resolved).toList()
          ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));

    return SafeArea(
      top: false,
      child: DraggableScrollableSheet(
        initialChildSize: 0.85,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) {
          return Column(
            children: [
              // ── a. Header row + privacy subtitle + toggle ──────────────
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.sm,
                  AppSpacing.lg,
                  AppSpacing.xs,
                ),
                child: Row(
                  children: [
                    const Icon(Icons.shield_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'What Copilot knows about me',
                            style: theme.textTheme.titleLarge,
                          ),
                          Text(
                            'Stored only on this device. Sent with your '
                            'messages as context; never saved by the server.',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: cs.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Switch(
                      value: memoryEnabled,
                      onChanged: (v) {
                        HapticFeedback.selectionClick();
                        ref.read(memoryEnabledProvider.notifier).setEnabled(v);
                      },
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
                    // ── b. PROFILE ────────────────────────────────────────
                    const SectionHeader('Profile'),
                    _ProfileRowTile(
                      icon: Icons.person_outline,
                      label: 'Sponsor',
                      value: memory.profile.sponsor,
                      onEdit: () async {
                        HapticFeedback.selectionClick();
                        final v = await _prompt(
                          context,
                          title: 'Sponsor',
                          label: 'Who is it?',
                          initial: memory.profile.sponsor ?? '',
                        );
                        if (v != null) {
                          await memoryNotifier.updateProfile(sponsor: v);
                        }
                      },
                    ),
                    _ProfileRowTile(
                      icon: Icons.groups_outlined,
                      label: 'Home group',
                      value: memory.profile.homeGroup,
                      onEdit: () async {
                        HapticFeedback.selectionClick();
                        final v = await _prompt(
                          context,
                          title: 'Home group',
                          label: 'Which group is home?',
                          initial: memory.profile.homeGroup ?? '',
                        );
                        if (v != null) {
                          await memoryNotifier.updateProfile(homeGroup: v);
                        }
                      },
                    ),
                    _ProfileRowTile(
                      icon: Icons.flag_outlined,
                      label: 'Goal',
                      value: memory.profile.goal,
                      onEdit: () async {
                        HapticFeedback.selectionClick();
                        final v = await _prompt(
                          context,
                          title: 'Goal',
                          label: 'What are you working toward?',
                          initial: memory.profile.goal ?? '',
                        );
                        if (v != null) {
                          await memoryNotifier.updateProfile(goal: v);
                        }
                      },
                    ),
                    Padding(
                      padding: const EdgeInsets.only(top: AppSpacing.sm),
                      child: _TriggerChips(
                        triggers: memory.profile.triggers,
                        onAdd: () async {
                          HapticFeedback.selectionClick();
                          final v = await _prompt(
                            context,
                            title: 'Add a trigger',
                            label: 'What situations are risky for you?',
                          );
                          if (v != null && v.isNotEmpty) {
                            await memoryNotifier.updateProfile(
                              triggers: [...memory.profile.triggers, v],
                            );
                          }
                        },
                        onDelete: (i) async {
                          HapticFeedback.selectionClick();
                          final next = List<String>.of(memory.profile.triggers)
                            ..removeAt(i);
                          await memoryNotifier.updateProfile(triggers: next);
                        },
                      ),
                    ),

                    // ── c. FACTS ──────────────────────────────────────────
                    const SectionHeader('Things Copilot remembers'),
                    if (memory.facts.isEmpty)
                      _EmptyHint(
                        text:
                            'Nothing yet. After a few conversations, '
                            'Copilot will start remembering durable things '
                            'here.',
                      )
                    else
                      ...memory.facts.reversed.map(
                        (f) => _FactRow(
                          fact: f,
                          onEdit: () async {
                            HapticFeedback.selectionClick();
                            final v = await _prompt(
                              context,
                              title: 'Edit memory',
                              label: 'How should this read?',
                              initial: f.text,
                            );
                            if (v == null || v.isEmpty) return;
                            // Edit = replace (remove + re-add keeps the
                            // dedupe constraint intact).
                            await memoryNotifier.removeFact(f.id);
                            await memoryNotifier.addFact(
                              v,
                              f.sourceConversationId,
                            );
                          },
                          onDelete: () async {
                            HapticFeedback.selectionClick();
                            await _confirm(
                              context,
                              title: 'Forget this?',
                              body: f.text,
                              onConfirm: () => memoryNotifier.removeFact(f.id),
                            );
                          },
                        ),
                      ),

                    // ── d. THREADS ────────────────────────────────────────
                    const SectionHeader('Open topics'),
                    if (openThreads.isEmpty)
                      _EmptyHint(text: 'No open topics right now.')
                    else
                      ...openThreads.map(
                        (t) => _ThreadCard(
                          thread: t,
                          onResume: () => _resumeThread(context, ref, t),
                          onMarkHandled: () async {
                            HapticFeedback.selectionClick();
                            await memoryNotifier.resolveThread(t.id);
                          },
                        ),
                      ),
                    if (resolvedThreads.isNotEmpty)
                      ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        title: Text(
                          'Handled',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: cs.onSurfaceVariant,
                          ),
                        ),
                        childrenPadding: const EdgeInsets.only(
                          bottom: AppSpacing.sm,
                        ),
                        children: [
                          for (final t in resolvedThreads)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              dense: true,
                              leading: const Icon(
                                Icons.check_circle_outline,
                                size: 20,
                              ),
                              title: Text(t.title),
                              subtitle:
                                  t.lastDetail.isEmpty
                                      ? null
                                      : Text(t.lastDetail),
                              trailing: Text(
                                agoFor(t.updatedAt),
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: cs.onSurfaceVariant,
                                ),
                              ),
                            ),
                        ],
                      ),

                    // ── e. DANGER ─────────────────────────────────────────
                    const SizedBox(height: AppSpacing.xl),
                    Center(
                      child: TextButton(
                        onPressed: () {
                          HapticFeedback.selectionClick();
                          _confirm(
                            context,
                            title: 'Forget everything?',
                            body:
                                'This erases everything Copilot remembers '
                                'about you on this device.',
                            onConfirm: () async {
                              await memoryNotifier.forgetAll();
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                    content: Text(
                                      'Personal memory erased from this '
                                      'device.',
                                    ),
                                  ),
                                );
                              }
                            },
                          );
                        },
                        style: TextButton.styleFrom(
                          foregroundColor: AppColors.error,
                        ),
                        child: const Text('Forget everything'),
                      ),
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

/// Tap-to-edit profile row; shows a muted "(not set)" placeholder when unset.
class _ProfileRowTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String? value;
  final Future<void> Function() onEdit;

  const _ProfileRowTile({
    required this.icon,
    required this.label,
    required this.value,
    required this.onEdit,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final hasValue = value != null && value!.trim().isNotEmpty;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icon, color: cs.onSurfaceVariant),
      title: Text(
        hasValue ? value! : '$label (not set)',
        style: theme.textTheme.bodyMedium?.copyWith(
          color: hasValue ? null : cs.onSurfaceVariant,
        ),
      ),
      subtitle: Text(label, style: theme.textTheme.bodySmall),
      trailing: const Icon(Icons.chevron_right, size: 20),
      onTap: onEdit,
    );
  }
}

/// Triggers as InputChips (delete 'x') + an "Add trigger" chip.
class _TriggerChips extends StatelessWidget {
  final List<String> triggers;
  final Future<void> Function() onAdd;
  final void Function(int index) onDelete;

  const _TriggerChips({
    required this.triggers,
    required this.onAdd,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.sm,
      children: [
        for (var i = 0; i < triggers.length; i++)
          InputChip(
            label: Text(triggers[i]),
            onDeleted: () => onDelete(i),
            deleteIconColor: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ActionChip(
          avatar: const Icon(Icons.add, size: 16),
          label: const Text('Add trigger'),
          onPressed: onAdd,
        ),
      ],
    );
  }
}

/// A single fact row: text + created-ago caption, edit icon, delete via
/// long-press -> confirm dialog. Deliberately NOT Dismissible: an accidental
/// side-swipe must never destroy a memory.
class _FactRow extends StatelessWidget {
  final MemoryFact fact;
  final Future<void> Function() onEdit;
  final Future<void> Function() onDelete;

  const _FactRow({
    required this.fact,
    required this.onEdit,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListTile(
      contentPadding: EdgeInsets.zero,
      dense: true,
      title: Text(fact.text),
      subtitle: Text(agoFor(fact.createdAt), style: theme.textTheme.bodySmall),
      trailing: IconButton(
        icon: const Icon(Icons.edit_outlined, size: 20),
        tooltip: 'Edit',
        onPressed: onEdit,
      ),
      onLongPress: onDelete,
    );
  }
}

/// An open thread card: bold title, muted last detail, relative age;
/// tap -> resume; 'Mark handled' action per card.
class _ThreadCard extends StatelessWidget {
  final MemoryThread thread;
  final VoidCallback onResume;
  final Future<void> Function() onMarkHandled;

  const _ThreadCard({
    required this.thread,
    required this.onResume,
    required this.onMarkHandled,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: InkWell(
        onTap: onResume,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.history, size: 20),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      thread.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Text(
                    agoFor(thread.updatedAt),
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: cs.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
              if (thread.lastDetail.trim().isNotEmpty) ...[
                const SizedBox(height: AppSpacing.xs),
                Text(
                  thread.lastDetail,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: cs.onSurfaceVariant,
                  ),
                ),
              ],
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: onMarkHandled,
                  child: Text(
                    'Mark handled',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: cs.onSurfaceVariant,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The empty-facts explanatory copy.
class _EmptyHint extends StatelessWidget {
  final String text;
  const _EmptyHint({required this.text});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Text(
        text,
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
          fontStyle: FontStyle.italic,
        ),
      ),
    );
  }
}
