/// In-app passage reader for the knowledge graph.
///
/// Fetches a JSON reading window (`/api/doc/{id}/window`) around a passage so
/// the literature can be read in place on every platform — the website has no
/// offline pack, so this replaces the old "open a new tab" fallback. The
/// reader also lists the *other* topics that occur in the passage, which is
/// how the graph lets you hop from one topic to the next through a book.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/features/library/offline_reader.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:url_launcher/url_launcher.dart';

import 'graph_api.dart';
import 'graph_models.dart';

class PassageReaderSheet extends ConsumerStatefulWidget {
  final GraphApi api;
  final Passage passage;

  /// The topic the user arrived from (highlighted among the chips), if any.
  final String? fromTopicId;
  final void Function(TopicRef topic) onTopic;
  final void Function(String prompt)? onAsk;

  const PassageReaderSheet({
    super.key,
    required this.api,
    required this.passage,
    required this.onTopic,
    this.fromTopicId,
    this.onAsk,
  });

  @override
  ConsumerState<PassageReaderSheet> createState() => _PassageReaderSheetState();
}

class _PassageReaderSheetState extends ConsumerState<PassageReaderSheet> {
  DocWindow? _window;
  String? _error;
  bool _loading = true;
  bool _extending = false;
  bool _saved = false;

  @override
  void initState() {
    super.initState();
    _load();
    _saved = ref.read(savedPassagesProvider.notifier).isSaved(_asSource());
  }

  Future<void> _load() async {
    final p = widget.passage;
    if (p.docId == null || p.docId!.isEmpty) {
      setState(() {
        _loading = false;
        _error = 'This passage has no reader link.';
      });
      return;
    }
    try {
      final w = await widget.api.window(p.docId!, p.blockIds, radius: 6, anchor: p.excerpt);
      if (!mounted) return;
      setState(() {
        _window = w.found ? w : null;
        _loading = false;
        if (!w.found) {
          _error = 'The exact spot in the book could not be located, so here is the passage as indexed.';
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load the passage. $e';
      });
    }
  }

  /// Extend the window backwards (earlier in the book) or forwards.
  Future<void> _extend({required bool forward}) async {
    final w = _window;
    if (w == null || _extending) return;
    final anchor = forward ? w.nextBlock : w.prevBlock;
    if (anchor == null) return;
    setState(() => _extending = true);
    try {
      final more = await widget.api.window(w.docId, [anchor], radius: 6);
      if (!mounted) return;
      final existing = w.blocks.map((b) => b.id).toSet();
      final fresh = more.blocks.where((b) => !existing.contains(b.id)).map(
            (b) => WindowBlock(id: b.id, type: b.type, text: b.text, printedPage: b.printedPage),
          );
      final blocks = forward ? [...w.blocks, ...fresh] : [...fresh, ...w.blocks];
      setState(() {
        _window = DocWindow(
          docId: w.docId,
          title: w.title,
          author: w.author,
          found: true,
          heading: forward ? w.heading : (more.heading ?? w.heading),
          start: forward ? w.start : more.start,
          end: forward ? more.end : w.end,
          total: w.total,
          prevBlock: forward ? w.prevBlock : more.prevBlock,
          nextBlock: forward ? more.nextBlock : w.nextBlock,
          blocks: blocks,
        );
      });
    } catch (_) {
      // Leave the window as it was; the button stays available.
    } finally {
      if (mounted) setState(() => _extending = false);
    }
  }

  Source _asSource() {
    final p = widget.passage;
    return Source(
      source: '${p.bookTitle}.pdf',
      similarity: 1,
      url: '',
      excerpt: p.excerpt,
      docId: p.docId,
      blockIds: p.blockIds,
      page: p.printedPage,
    );
  }

  Future<void> _toggleSave() async {
    final notifier = ref.read(savedPassagesProvider.notifier);
    final s = _asSource();
    if (_saved) {
      await notifier.remove(s);
    } else {
      await notifier.save(s);
    }
    if (mounted) setState(() => _saved = !_saved);
  }

  Future<void> _openFullReader() async {
    final p = widget.passage;
    if (p.docId == null) return;
    final repo = ref.read(libraryRepositoryProvider);
    final installed = await repo.isPackInstalled;
    if (!mounted) return;
    if (installed) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => OfflineReaderScreen(
            docId: p.docId!,
            title: p.bookTitle,
            highlightBlockIds: p.blockIds,
          ),
        ),
      );
      return;
    }
    final uri = Uri.tryParse(widget.api.readerUrl(p.docId!, p.blockIds));
    if (uri != null) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final p = widget.passage;
    final w = _window;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // ── Header ─────────────────────────────────────────────────────────
        Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.sm, AppSpacing.sm),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 3),
                child: Icon(Icons.menu_book_outlined, color: AppColors.accent, size: 22),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      w?.title ?? p.bookTitle,
                      style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      [
                        if ((w?.author ?? '').isNotEmpty) w!.author,
                        if ((w?.heading ?? p.section ?? '').isNotEmpty) (w?.heading ?? p.section)!,
                        if (p.printedPage != null) 'p. ${p.printedPage}',
                      ].join(' · '),
                      style: theme.textTheme.bodySmall,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: _saved ? 'Remove from saved passages' : 'Save passage',
                icon: Icon(_saved ? Icons.bookmark : Icons.bookmark_outline,
                    color: _saved ? AppColors.gold : null),
                onPressed: _toggleSave,
              ),
              IconButton(
                tooltip: 'Close',
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
        ),

        // ── Topic hops ─────────────────────────────────────────────────────
        if (p.topics.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.sm),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('ALSO IN THIS PASSAGE — TAP TO JUMP',
                    style: theme.textTheme.labelSmall?.copyWith(
                      letterSpacing: 0.8,
                      color: theme.colorScheme.onSurfaceVariant,
                    )),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final t in p.topics)
                      TopicChip(
                        label: t.label,
                        color: t.color,
                        onTap: () {
                          Navigator.of(context).pop();
                          widget.onTopic(t);
                        },
                      ),
                  ],
                ),
              ],
            ),
          ),
        const Divider(height: 1),

        // ── Body ───────────────────────────────────────────────────────────
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Padding(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(_error!, style: theme.textTheme.bodyMedium),
                          const SizedBox(height: AppSpacing.md),
                          Text('"${p.excerpt}"',
                              style: theme.textTheme.bodyMedium?.copyWith(fontStyle: FontStyle.italic)),
                        ],
                      ),
                    )
                  : ListView(
                      controller: PrimaryScrollController.maybeOf(context),
                      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.xl),
                      children: [
                        if (w?.prevBlock != null)
                          Center(
                            child: TextButton.icon(
                              onPressed: _extending ? null : () => _extend(forward: false),
                              icon: const Icon(Icons.expand_less, size: 18),
                              label: const Text('Read earlier'),
                            ),
                          ),
                        for (final b in w!.blocks) _ReaderBlock(block: b, isDark: isDark),
                        if (w.nextBlock != null)
                          Center(
                            child: TextButton.icon(
                              onPressed: _extending ? null : () => _extend(forward: true),
                              icon: const Icon(Icons.expand_more, size: 18),
                              label: const Text('Keep reading'),
                            ),
                          ),
                      ],
                    ),
        ),

        // ── Actions ────────────────────────────────────────────────────────
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.sm, AppSpacing.lg, AppSpacing.sm),
            child: Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.auto_stories_outlined, size: 18),
                    label: const Text('Open book'),
                    onPressed: p.docId == null ? null : _openFullReader,
                  ),
                ),
                if (widget.onAsk != null) ...[
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: FilledButton.icon(
                      icon: const Icon(Icons.auto_awesome, size: 18),
                      label: const Text('Ask about this'),
                      onPressed: () {
                        final where = [p.bookTitle, if (p.section != null) p.section!].join(', ');
                        widget.onAsk!('Help me understand this passage from $where: "${p.excerpt}"');
                      },
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _ReaderBlock extends StatelessWidget {
  final WindowBlock block;
  final bool isDark;
  const _ReaderBlock({required this.block, required this.isDark});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final base = theme.textTheme.bodyMedium?.copyWith(fontFamily: 'Georgia', height: 1.55, fontSize: 16);
    Widget child;
    switch (block.type) {
      case 'heading':
        child = Padding(
          padding: const EdgeInsets.only(top: 14, bottom: 4),
          child: Text(block.text,
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700, letterSpacing: 0.3)),
        );
      case 'epigraph':
        child = Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          child: Text(block.text, style: base?.copyWith(fontStyle: FontStyle.italic, fontSize: 15)),
        );
      case 'footnote':
        child = Text(block.text, style: base?.copyWith(fontSize: 13, color: theme.colorScheme.onSurfaceVariant));
      default:
        child = Text(block.text, style: base);
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: block.highlight ? const EdgeInsets.fromLTRB(10, 8, 10, 8) : EdgeInsets.zero,
      decoration: block.highlight
          ? BoxDecoration(
              color: AppColors.highlightBg(isDark),
              borderRadius: BorderRadius.circular(8),
              border: Border(left: BorderSide(color: AppColors.accent, width: 3)),
            )
          : null,
      child: child,
    );
  }
}

/// Small coloured topic chip used across the graph panels and the reader.
class TopicChip extends StatelessWidget {
  final String label;
  final Color color;
  final VoidCallback? onTap;
  final bool selected;
  final String? trailing;

  const TopicChip({
    super.key,
    required this.label,
    required this.color,
    this.onTap,
    this.selected = false,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    return Material(
      color: selected ? color.withValues(alpha: isDark ? 0.45 : 0.30) : color.withValues(alpha: isDark ? 0.20 : 0.14),
      borderRadius: BorderRadius.circular(999),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 6),
              Text(
                label,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurface,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                ),
              ),
              if (trailing != null) ...[
                const SizedBox(width: 5),
                Text(trailing!,
                    style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
