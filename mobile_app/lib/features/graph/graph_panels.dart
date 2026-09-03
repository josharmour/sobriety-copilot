/// Detail panel widgets for the knowledge graph screen.
///
/// The canvas shows *where* you are; these panels show *what is there* —
/// the topic's books and passages, a book's chapters, search results — and
/// every element is a link deeper into the literature.
library;

import 'package:flutter/material.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

import 'graph_models.dart';
import 'passage_reader.dart';

/// Everything a panel can ask the screen to do.
class GraphActions {
  final void Function(String topicId, {String? bookId}) focusTopic;
  final void Function(String bookId) focusBook;
  final void Function(String topicId, {String? bookId, int? section, String? sectionTitle}) openPassages;
  final void Function(Passage passage, {String? fromTopic}) openPassage;
  final VoidCallback showOverview;
  final void Function(String? group) filterGroup;
  final void Function(String prompt)? ask;

  const GraphActions({
    required this.focusTopic,
    required this.focusBook,
    required this.openPassages,
    required this.openPassage,
    required this.showOverview,
    required this.filterGroup,
    this.ask,
  });
}

String _n(int n) => n >= 1000 ? '${(n / 1000).toStringAsFixed(n >= 10000 ? 0 : 1)}k' : '$n';

// ── Shared pieces ────────────────────────────────────────────────────────────

class PanelHeader extends StatelessWidget {
  final Widget leading;
  final String title;
  final String? subtitle;
  final List<Widget> actions;
  const PanelHeader({
    super.key,
    required this.leading,
    required this.title,
    this.subtitle,
    this.actions = const [],
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.sm, AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(padding: const EdgeInsets.only(top: 2), child: leading),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis),
                if (subtitle != null && subtitle!.isNotEmpty)
                  Text(subtitle!, style: theme.textTheme.bodySmall, maxLines: 3, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          ...actions,
        ],
      ),
    );
  }
}

class SectionLabel extends StatelessWidget {
  final String text;
  final Widget? trailing;
  const SectionLabel(this.text, {super.key, this.trailing});
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 6),
      child: Row(
        children: [
          Expanded(
            child: Text(text.toUpperCase(),
                style: theme.textTheme.labelSmall?.copyWith(
                  letterSpacing: 0.9,
                  fontWeight: FontWeight.w700,
                  color: theme.colorScheme.onSurfaceVariant,
                )),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class GroupDot extends StatelessWidget {
  final Color color;
  final double size;
  const GroupDot(this.color, {super.key, this.size = 14});
  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
          boxShadow: [BoxShadow(color: color.withValues(alpha: 0.5), blurRadius: 6)],
        ),
      );
}

class CategoryBadge extends StatelessWidget {
  final String label;
  const CategoryBadge(this.label, {super.key});
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (label.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Text(label, style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
    );
  }
}

/// One passage: locator, excerpt, and the topics it also touches.
class PassageCard extends StatelessWidget {
  final Passage passage;
  final GraphActions actions;
  final String? fromTopic;
  final bool showBook;
  const PassageCard({
    super.key,
    required this.passage,
    required this.actions,
    this.fromTopic,
    this.showBook = false,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = passage;
    final locator = [
      if (showBook) p.bookTitle,
      if (p.locator.isNotEmpty) p.locator,
    ].join(' · ');
    return Card(
      margin: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.sm),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => actions.openPassage(p, fromTopic: fromTopic),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.sm),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      locator.isEmpty ? 'Passage' : locator,
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                        fontWeight: FontWeight.w600,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  if (p.similarity != null)
                    Text('${(p.similarity! * 100).round()}%',
                        style: theme.textTheme.labelSmall?.copyWith(color: AppColors.accent)),
                  const SizedBox(width: 4),
                  Icon(Icons.chevron_right, size: 18, color: theme.colorScheme.onSurfaceVariant),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                p.excerpt,
                style: theme.textTheme.bodyMedium?.copyWith(fontFamily: 'Georgia', height: 1.4),
                maxLines: 5,
                overflow: TextOverflow.ellipsis,
              ),
              if (p.topics.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final t in p.topics.take(5))
                      TopicChip(
                        label: t.label,
                        color: t.color,
                        onTap: () => actions.focusTopic(t.id, bookId: p.bookId),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

// ── Building / loading ───────────────────────────────────────────────────────

class BuildingView extends StatelessWidget {
  final String status;
  final int progress;
  final String? error;
  final VoidCallback onRetry;
  const BuildingView({super.key, required this.status, required this.progress, this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final building = error == null;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(building ? Icons.hub_outlined : Icons.cloud_off_outlined, size: 44, color: AppColors.accent),
            const SizedBox(height: AppSpacing.md),
            Text(
              building ? 'Mapping the library…' : 'The knowledge graph is unavailable',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              building
                  ? 'The server is linking every topic to every passage in the literature. This takes a few seconds after an index rebuild.'
                  : error!,
              style: theme.textTheme.bodySmall,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.lg),
            if (building)
              SizedBox(
                width: 220,
                child: LinearProgressIndicator(value: progress > 0 ? progress / 100 : null, minHeight: 6),
              )
            else
              FilledButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('Try again')),
            if (building && status.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(status.replaceFirst('building: ', ''), style: theme.textTheme.labelSmall),
            ],
          ],
        ),
      ),
    );
  }
}

// ── Overview ─────────────────────────────────────────────────────────────────

class OverviewPanel extends StatelessWidget {
  final GraphMap map;
  final String? groupFilter;
  final GraphActions actions;
  final ScrollController controller;
  const OverviewPanel({
    super.key,
    required this.map,
    required this.groupFilter,
    required this.actions,
    required this.controller,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final byGroup = <String, List<TopicNode>>{};
    for (final t in map.topics) {
      byGroup.putIfAbsent(t.group, () => []).add(t);
    }
    final popular = [...map.topics]..sort((a, b) => b.mentions.compareTo(a.mentions));
    final Iterable<TopicNode> shownTopics =
        groupFilter == null ? popular.take(18) : (byGroup[groupFilter] ?? const <TopicNode>[]);
    return ListView(
      controller: controller,
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      children: [
        PanelHeader(
          leading: const Icon(Icons.hub, color: AppColors.accent),
          title: 'The whole library, mapped',
          subtitle:
              '${map.topics.length} topics · ${map.books.length} books · ${_n(map.passageCount)} passages. '
              'Tap a topic to see where it lives in the literature and which topics it leads to.',
        ),
        const SectionLabel('Themes'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final g in map.groups)
                TopicChip(
                  label: g.label,
                  color: groupColor(g.id),
                  selected: groupFilter == g.id,
                  trailing: '${byGroup[g.id]?.length ?? 0}',
                  onTap: () => actions.filterGroup(groupFilter == g.id ? null : g.id),
                ),
            ],
          ),
        ),
        SectionLabel(groupFilter == null ? 'Most discussed' : 'Topics in this theme'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final t in shownTopics)
                TopicChip(
                  label: t.label,
                  color: t.color,
                  trailing: _n(t.mentions),
                  onTap: () => actions.focusTopic(t.id),
                ),
            ],
          ),
        ),
        const SectionLabel('Books'),
        for (final b in map.books)
          ListTile(
            dense: true,
            leading: Icon(Icons.menu_book_outlined, color: theme.colorScheme.onSurfaceVariant),
            title: Text(b.title, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text(
              [if (b.byline.isNotEmpty) b.byline, '${_n(b.passages)} passages'].join(' · '),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            trailing: const Icon(Icons.chevron_right, size: 18),
            onTap: () => actions.focusBook(b.id),
          ),
      ],
    );
  }
}

// ── Topic ────────────────────────────────────────────────────────────────────

class TopicPanel extends StatelessWidget {
  final TopicDetail detail;
  final GraphActions actions;
  final ScrollController controller;
  final String? highlightBookId;
  const TopicPanel({
    super.key,
    required this.detail,
    required this.actions,
    required this.controller,
    this.highlightBookId,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final t = detail.topic;
    final books = [...detail.books];
    if (highlightBookId != null) {
      final i = books.indexWhere((b) => b.id == highlightBookId);
      if (i > 0) books.insert(0, books.removeAt(i));
    }
    return ListView(
      controller: controller,
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      children: [
        PanelHeader(
          leading: GroupDot(t.color, size: 16),
          title: t.label,
          subtitle: '${t.blurb}\n${_n(t.mentions)} passages across ${t.books} books',
          actions: [
            if (actions.ask != null)
              IconButton(
                tooltip: 'Ask about ${t.label}',
                icon: const Icon(Icons.auto_awesome, color: AppColors.accent),
                onPressed: () => actions.ask!('What does the recovery literature teach about ${t.label.toLowerCase()}?'),
              ),
          ],
        ),
        if (detail.related.isNotEmpty) ...[
          const SectionLabel('Leads to'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final r in detail.related)
                  TopicChip(
                    label: r.label,
                    color: r.color,
                    trailing: '${r.shared}',
                    onTap: () => actions.focusTopic(r.id),
                  ),
              ],
            ),
          ),
        ],
        SectionLabel('In the literature', trailing: Text('${detail.totalBooks} books', style: theme.textTheme.labelSmall)),
        for (final b in books)
          _TopicBookBlock(
            book: b,
            topic: t,
            actions: actions,
            expanded: highlightBookId == null || b.id == highlightBookId,
          ),
      ],
    );
  }
}

class _TopicBookBlock extends StatelessWidget {
  final BookNode book;
  final TopicNode topic;
  final GraphActions actions;
  final bool expanded;
  const _TopicBookBlock({required this.book, required this.topic, required this.actions, required this.expanded});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          dense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          leading: Icon(Icons.menu_book_outlined, color: theme.colorScheme.onSurfaceVariant),
          title: Text(book.title, maxLines: 1, overflow: TextOverflow.ellipsis,
              style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          subtitle: Text(
            [if (book.byline.isNotEmpty) book.byline, '${book.count} passages'].join(' · '),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          trailing: TextButton(
            onPressed: () => actions.openPassages(topic.id, bookId: book.id),
            child: const Text('All'),
          ),
          onTap: () => actions.focusBook(book.id),
        ),
        if (expanded) ...[
          if (book.sections.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.sm),
              child: Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final s in book.sections)
                    ActionChip(
                      avatar: const Icon(Icons.bookmark_border, size: 14),
                      label: Text('${s.title} · ${s.count}', maxLines: 1, overflow: TextOverflow.ellipsis),
                      labelStyle: theme.textTheme.labelSmall,
                      visualDensity: VisualDensity.compact,
                      onPressed: () => actions.openPassages(topic.id,
                          bookId: book.id, section: s.index, sectionTitle: s.title),
                    ),
                ],
              ),
            ),
          for (final p in book.topicPassages) PassageCard(passage: p, actions: actions, fromTopic: topic.id),
        ],
        const SizedBox(height: 4),
      ],
    );
  }
}

// ── Book ─────────────────────────────────────────────────────────────────────

class BookPanel extends StatelessWidget {
  final BookDetail detail;
  final GraphActions actions;
  final ScrollController controller;
  const BookPanel({super.key, required this.detail, required this.actions, required this.controller});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final b = detail.book;
    return ListView(
      controller: controller,
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      children: [
        PanelHeader(
          leading: const Icon(Icons.menu_book, color: AppColors.gold),
          title: b.title,
          subtitle: [if (b.author.isNotEmpty) b.author, '${_n(b.passages)} passages'].join(' · '),
          actions: [
            Padding(padding: const EdgeInsets.only(top: 4, right: 8), child: CategoryBadge(b.categoryLabel)),
          ],
        ),
        const SectionLabel('What this book talks about'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final t in detail.topics)
                TopicChip(
                  label: t.label,
                  color: t.color,
                  trailing: '${t.count}',
                  onTap: () => actions.focusTopic(t.id, bookId: b.id),
                ),
            ],
          ),
        ),
        if (detail.sections.isNotEmpty) ...[
          SectionLabel('Chapters', trailing: Text('${detail.sections.length}', style: theme.textTheme.labelSmall)),
          for (final s in detail.sections)
            ListTile(
              dense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              title: Text(s.title, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: s.topics.isEmpty
                  ? null
                  : Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Wrap(
                        spacing: 4,
                        runSpacing: 4,
                        children: [
                          for (final t in s.topics)
                            TopicChip(
                              label: t.label,
                              color: t.color,
                              onTap: () => actions.openPassages(t.id,
                                  bookId: b.id, section: s.index, sectionTitle: s.title),
                            ),
                        ],
                      ),
                    ),
              trailing: s.printedPage == null
                  ? const Icon(Icons.chevron_right, size: 18)
                  : Text('p. ${s.printedPage}', style: theme.textTheme.labelSmall),
              onTap: b.docId == null || s.blockId.isEmpty
                  ? null
                  : () => actions.openPassage(Passage(
                        chunkId: '',
                        bookId: b.id,
                        bookTitle: b.title,
                        docId: b.docId,
                        blockIds: [s.blockId],
                        section: s.title,
                        printedPage: s.printedPage,
                        excerpt: s.title,
                      )),
            ),
        ],
      ],
    );
  }
}

// ── Passages list (topic × book [× chapter]) ─────────────────────────────────

class PassagesPanel extends StatelessWidget {
  final PassagePage page;
  final List<Passage> loaded;
  final String? sectionTitle;
  final bool loadingMore;
  final GraphActions actions;
  final ScrollController controller;
  final VoidCallback onBack;
  final VoidCallback onLoadMore;
  final void Function(String sort) onSort;

  const PassagesPanel({
    super.key,
    required this.page,
    required this.loaded,
    required this.sectionTitle,
    required this.loadingMore,
    required this.actions,
    required this.controller,
    required this.onBack,
    required this.onLoadMore,
    required this.onSort,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final t = page.topic;
    final where = page.book == null ? 'everywhere' : page.book!.title;
    return ListView(
      controller: controller,
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      children: [
        PanelHeader(
          leading: IconButton(
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Back',
            onPressed: onBack,
          ),
          title: '${t.label} in $where',
          subtitle: [
            if (sectionTitle != null) sectionTitle!,
            '${page.total} passages',
          ].join(' · '),
          actions: [
            if (page.book != null)
              IconButton(
                tooltip: 'About this book',
                icon: const Icon(Icons.menu_book_outlined),
                onPressed: () => actions.focusBook(page.book!.id),
              ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'score', label: Text('Best first'), icon: Icon(Icons.star_outline, size: 16)),
              ButtonSegment(value: 'position', label: Text('Book order'), icon: Icon(Icons.format_list_numbered, size: 16)),
            ],
            selected: {page.sort},
            showSelectedIcon: false,
            style: const ButtonStyle(visualDensity: VisualDensity.compact),
            onSelectionChanged: (s) => onSort(s.first),
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        for (final p in loaded) PassageCard(passage: p, actions: actions, fromTopic: t.id, showBook: page.book == null),
        if (loaded.length < page.total)
          Center(
            child: loadingMore
                ? const Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator(strokeWidth: 2))
                : TextButton.icon(
                    onPressed: onLoadMore,
                    icon: const Icon(Icons.expand_more),
                    label: Text('Load more (${page.total - loaded.length} left)'),
                  ),
          ),
        if (loaded.isEmpty)
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Text('No passages here.', style: theme.textTheme.bodySmall),
          ),
      ],
    );
  }
}

// ── Search ───────────────────────────────────────────────────────────────────

class SearchPanel extends StatelessWidget {
  final GraphSearchResult result;
  final GraphActions actions;
  final ScrollController controller;
  const SearchPanel({super.key, required this.result, required this.actions, required this.controller});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final noTopics = result.topics.isEmpty && result.suggestedTopics.isEmpty;
    return ListView(
      controller: controller,
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      children: [
        PanelHeader(
          leading: const Icon(Icons.search, color: AppColors.accent),
          title: '“${result.query}”',
          subtitle: '${result.passages.length} passages · ${result.topics.length + result.suggestedTopics.length} topics',
          actions: [
            IconButton(
              tooltip: 'Back to the map',
              icon: const Icon(Icons.hub_outlined),
              onPressed: actions.showOverview,
            ),
          ],
        ),
        if (result.topics.isNotEmpty) ...[
          const SectionLabel('Matching topics'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in result.topics)
                  TopicChip(label: t.label, color: t.color, trailing: _n(t.mentions), onTap: () => actions.focusTopic(t.id)),
              ],
            ),
          ),
        ],
        if (result.suggestedTopics.isNotEmpty) ...[
          const SectionLabel('These passages point to'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in result.suggestedTopics)
                  TopicChip(label: t.label, color: t.color, onTap: () => actions.focusTopic(t.id)),
              ],
            ),
          ),
        ],
        if (result.passages.isNotEmpty) const SectionLabel('Passages'),
        for (final p in result.passages) PassageCard(passage: p, actions: actions, showBook: true),
        if (result.passages.isEmpty && noTopics)
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Text('Nothing matched. Try a feeling, a Step, or a phrase from the literature.',
                style: theme.textTheme.bodyMedium),
          ),
      ],
    );
  }
}
