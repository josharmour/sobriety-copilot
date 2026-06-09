import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Persists and exposes the list of saved conversations.
///
/// Backed by [SharedPreferences] under [prefsKey]. The list is kept sorted
/// most-recently-updated first so the history sheet shows fresh chats on top.
class ConversationsNotifier extends Notifier<List<Conversation>> {
  static const String prefsKey = 'conversations_v1';

  SharedPreferences get _prefs => ref.read(sharedPreferencesProvider);

  @override
  List<Conversation> build() {
    return _load();
  }

  List<Conversation> _load() {
    final raw = _prefs.getString(prefsKey);
    if (raw == null || raw.isEmpty) return const [];
    try {
      final decoded = json.decode(raw);
      if (decoded is! List) return const [];
      final list = <Conversation>[];
      for (final item in decoded) {
        if (item is Map<String, dynamic>) {
          try {
            list.add(Conversation.fromJson(item));
          } catch (_) {
            // skip malformed entries
          }
        }
      }
      _sort(list);
      return list;
    } catch (_) {
      return const [];
    }
  }

  void _sort(List<Conversation> list) {
    list.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  }

  Future<void> _persist() async {
    final data = json.encode(state.map((c) => c.toJson()).toList());
    await _prefs.setString(prefsKey, data);
  }

  /// Save a new conversation or replace an existing one with the same id.
  /// Conversations with no messages are not persisted (mirrors the web app
  /// which never stores empty "New conversation" shells).
  Future<void> upsert(Conversation conversation) async {
    if (conversation.messages.isEmpty) {
      // Drop any previously-stored copy that is now empty.
      if (state.any((c) => c.id == conversation.id)) {
        await delete(conversation.id);
      }
      return;
    }
    final next = List<Conversation>.from(state);
    final idx = next.indexWhere((c) => c.id == conversation.id);
    if (idx >= 0) {
      next[idx] = conversation;
    } else {
      next.add(conversation);
    }
    _sort(next);
    state = next;
    await _persist();
  }

  /// Remove a conversation by id.
  Future<void> delete(String id) async {
    final next = state.where((c) => c.id != id).toList();
    if (next.length == state.length) return;
    state = next;
    await _persist();
  }

  /// Remove all saved conversations.
  Future<void> clearAll() async {
    if (state.isEmpty) return;
    state = const [];
    await _persist();
  }

  /// Look up a stored conversation by id, or null when absent.
  Conversation? byId(String id) {
    for (final c in state) {
      if (c.id == id) return c;
    }
    return null;
  }
}

/// Bottom-sheet listing saved conversations with switch / new / delete actions.
class ConversationsSheet extends ConsumerWidget {
  const ConversationsSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final conversations = ref.watch(conversationsProvider);
    final activeId = ref.watch(
      chatNotifierProvider.select((s) => s.conversationId),
    );

    return SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.lg,
              AppSpacing.sm,
              AppSpacing.sm,
            ),
            child: Row(
              children: [
                const Expanded(child: SectionHeader('Conversations')),
                if (conversations.isNotEmpty)
                  TextButton.icon(
                    onPressed: () => _confirmClearAll(context, ref),
                    icon: const Icon(Icons.delete_sweep_outlined, size: 18),
                    label: const Text('Clear'),
                    style: TextButton.styleFrom(
                      foregroundColor: theme.colorScheme.error,
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: FilledButton.tonalIcon(
              onPressed: () {
                ref.read(chatNotifierProvider.notifier).startNew();
                Navigator.of(context).maybePop();
              },
              icon: const Icon(Icons.add_comment_outlined),
              label: const Text('New conversation'),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Flexible(
            child:
                conversations.isEmpty
                    ? const Padding(
                      padding: EdgeInsets.symmetric(
                        vertical: AppSpacing.xxl,
                        horizontal: AppSpacing.lg,
                      ),
                      child: Center(
                        child: Text(
                          'No conversations yet',
                          style: TextStyle(
                            color: AppColors.lightTextSecondary,
                          ),
                        ),
                      ),
                    )
                    : ListView.builder(
                      shrinkWrap: true,
                      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
                      itemCount: conversations.length,
                      itemBuilder: (context, i) {
                        final conv = conversations[i];
                        final active = conv.id == activeId;
                        return _ConversationTile(
                          conversation: conv,
                          active: active,
                          onTap: () {
                            ref
                                .read(chatNotifierProvider.notifier)
                                .loadConversation(conv);
                            Navigator.of(context).maybePop();
                          },
                          onDelete: () async {
                            if (active) {
                              ref
                                  .read(chatNotifierProvider.notifier)
                                  .startNew();
                            }
                            await ref
                                .read(conversationsProvider.notifier)
                                .delete(conv.id);
                          },
                        );
                      },
                    ),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmClearAll(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder:
          (ctx) => AlertDialog(
            title: const Text('Clear all conversations?'),
            content: const Text(
              'This permanently removes your saved chat history on this device. '
              'It cannot be undone.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(false),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: () => Navigator.of(ctx).pop(true),
                child: const Text('Clear all'),
              ),
            ],
          ),
    );
    if (ok == true) {
      ref.read(chatNotifierProvider.notifier).startNew();
      await ref.read(conversationsProvider.notifier).clearAll();
    }
  }
}

class _ConversationTile extends StatelessWidget {
  final Conversation conversation;
  final bool active;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  const _ConversationTile({
    required this.conversation,
    required this.active,
    required this.onTap,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final count = conversation.messages.length;
    return ListTile(
      selected: active,
      selectedTileColor: AppColors.accentSoft,
      leading: Icon(
        active ? Icons.chat_bubble : Icons.chat_bubble_outline,
        color: active ? AppColors.accent : theme.colorScheme.onSurfaceVariant,
      ),
      title: Text(
        conversation.title.isEmpty ? 'New conversation' : conversation.title,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          fontWeight: active ? FontWeight.w600 : FontWeight.w500,
        ),
      ),
      subtitle: Text(
        '${_relativeTime(conversation.updatedAt)} · '
        '$count message${count == 1 ? '' : 's'}',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: IconButton(
        icon: const Icon(Icons.delete_outline),
        tooltip: 'Delete',
        color: theme.colorScheme.error,
        onPressed: onDelete,
      ),
      onTap: onTap,
    );
  }

  String _relativeTime(DateTime t) {
    final now = DateTime.now();
    final diff = now.difference(t);
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return DateFormat.yMMMd().format(t);
  }
}
