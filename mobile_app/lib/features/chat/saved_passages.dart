import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Maximum number of saved passages retained (mirrors web app cap of 100).
const int _kMaxSavedPassages = 100;

/// Stable identity for a saved [Source]: its document key plus the excerpt.
/// Mirrors the web app, which de-dupes saved passages by passage text.
String _savedKey(Source s) => '${s.documentKey}::${s.excerpt}';

/// Citation-formatted share text for a passage (the sponsor/text-a-friend
/// workflow): quoted excerpt, title, printed page when known.
String shareTextFor(Source s) {
  final page = s.page?.toString() ?? '';
  final cite = page.isNotEmpty ? '${s.title}, p. $page' : s.title;
  return '"${s.excerpt.trim()}"\n— $cite';
}

/// Riverpod notifier backing the saved/bookmarked passages list.
///
/// Persisted to SharedPreferences as a JSON array of [Source.toJson] maps.
/// Newest items are kept at the front of the list.
class SavedPassagesNotifier extends Notifier<List<Source>> {
  static const String prefsKey = 'saved_passages_v1';

  @override
  List<Source> build() {
    final prefs = ref.read(sharedPreferencesProvider);
    final raw = prefs.getString(prefsKey);
    if (raw == null || raw.isEmpty) return const [];
    try {
      final decoded = json.decode(raw);
      if (decoded is! List) return const [];
      return decoded
          .whereType<Map>()
          .map((m) => Source.fromJson(Map<String, dynamic>.from(m)))
          .toList(growable: false);
    } catch (_) {
      return const [];
    }
  }

  Future<void> _persist() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final encoded = json.encode(state.map((s) => s.toJson()).toList());
    await prefs.setString(prefsKey, encoded);
  }

  /// Bookmarks [source]. De-dupes by [Source.documentKey] + excerpt; if it is
  /// already saved this is a no-op. Newest items go to the front; the list is
  /// capped at [_kMaxSavedPassages].
  Future<void> save(Source source) async {
    final key = _savedKey(source);
    if (state.any((s) => _savedKey(s) == key)) return;
    var next = [source, ...state];
    if (next.length > _kMaxSavedPassages) {
      next = next.sublist(0, _kMaxSavedPassages);
    }
    state = next;
    await _persist();
  }

  /// Removes [source] from the saved list (matched by document key + excerpt).
  Future<void> remove(Source source) async {
    final key = _savedKey(source);
    final next = state.where((s) => _savedKey(s) != key).toList();
    if (next.length == state.length) return;
    state = next;
    await _persist();
  }

  /// Whether [source] is currently saved.
  bool isSaved(Source source) {
    final key = _savedKey(source);
    return state.any((s) => _savedKey(s) == key);
  }

  /// Removes all saved passages.
  Future<void> clearAll() async {
    if (state.isEmpty) return;
    state = const [];
    await _persist();
  }
}

/// Bottom-sheet listing saved passages with open / remove / clear-all actions.
class SavedPassagesSheet extends ConsumerWidget {
  const SavedPassagesSheet({super.key});

  Future<void> _open(BuildContext context, Source source, String baseUrl) async {
    if (source.url.isEmpty) return;
    final uri = Uri.parse(source.renderUrl(baseUrl, highlight: source.excerpt));
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open the document.')),
      );
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final saved = ref.watch(savedPassagesProvider);
    final config = ref.watch(appConfigProvider);
    final theme = Theme.of(context);

    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.md,
              AppSpacing.sm,
              AppSpacing.xs,
            ),
            child: Row(
              children: [
                const Expanded(child: SectionHeader('Saved passages')),
                if (saved.isNotEmpty)
                  TextButton.icon(
                    onPressed: () =>
                        ref.read(savedPassagesProvider.notifier).clearAll(),
                    icon: const Icon(Icons.delete_sweep_outlined, size: 18),
                    label: const Text('Clear all'),
                  ),
              ],
            ),
          ),
          if (saved.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.lg,
                AppSpacing.lg,
                AppSpacing.xl,
              ),
              child: Text(
                'Star passages from a source to save them here.',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.textTheme.bodySmall?.color,
                ),
              ),
            )
          else
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.xs,
                  AppSpacing.lg,
                  AppSpacing.lg,
                ),
                itemCount: saved.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: AppSpacing.sm),
                itemBuilder: (context, i) {
                  final s = saved[i];
                  return _SavedPassageTile(
                    source: s,
                    onOpen: s.url.isEmpty
                        ? null
                        : () => _open(context, s, config.baseUrl),
                    onShare: () => SharePlus.instance.share(
                      ShareParams(text: shareTextFor(s)),
                    ),
                    onRemove: () =>
                        ref.read(savedPassagesProvider.notifier).remove(s),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _SavedPassageTile extends StatelessWidget {
  final Source source;
  final VoidCallback? onOpen;
  final VoidCallback onShare;
  final VoidCallback onRemove;

  const _SavedPassageTile({
    required this.source,
    required this.onOpen,
    required this.onShare,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final excerpt = source.excerpt;
    final preview = excerpt.length > 200 ? '${excerpt.substring(0, 200)}…' : excerpt;

    return Material(
      color: AppColors.accentSoft.withValues(alpha: 0.5),
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      child: InkWell(
        onTap: onOpen,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                preview,
                style: theme.textTheme.bodyMedium,
              ),
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      source.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: AppColors.accent,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    iconSize: 18,
                    tooltip: 'Share',
                    onPressed: onShare,
                    icon: const Icon(Icons.ios_share),
                  ),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    iconSize: 18,
                    tooltip: 'Remove',
                    onPressed: onRemove,
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
