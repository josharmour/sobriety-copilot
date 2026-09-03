import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

class OfflineReaderScreen extends ConsumerStatefulWidget {
  final String docId;
  final String title;
  final List<String>? highlightBlockIds;

  const OfflineReaderScreen({
    super.key,
    required this.docId,
    required this.title,
    this.highlightBlockIds,
  });

  @override
  ConsumerState<OfflineReaderScreen> createState() => _OfflineReaderScreenState();
}

class _OfflineReaderScreenState extends ConsumerState<OfflineReaderScreen> {
  /// Study-excerpt window: blocks shown on each side of the cited passage.
  /// The app is a study aide, not a reproduction of the book — the reader
  /// deliberately shows only an excerpt and urges purchase of the full work.
  static const int _excerptRadius = 30;

  bool _loading = true;
  String? _error;
  List<dynamic> _blocks = [];
  bool _moreBefore = false;
  bool _moreAfter = false;
  final Map<String, GlobalKey> _blockKeys = {};
  bool _hasScrolled = false;

  @override
  void initState() {
    super.initState();
    _loadManifest();
  }

  Future<void> _loadManifest() async {
    try {
      final repo = ref.read(libraryRepositoryProvider);
      final manifest = await repo.getManifest(widget.docId);
      if (manifest == null) {
        setState(() {
          _error = 'Book content not found locally.';
          _loading = false;
        });
        return;
      }

      final blocksList = manifest['blocks'] as List<dynamic>? ?? [];

      // Filter out headers, footers, garbage
      final filteredBlocks = blocksList.where((b) {
        final type = b['type']?.toString();
        return type != 'page_header' && type != 'page_footer' && type != 'garbage';
      }).toList();

      // Excerpt window centered on the cited passage (or the start of the
      // book when opened without a citation).
      var anchor = 0;
      final targets = widget.highlightBlockIds;
      if (targets != null && targets.isNotEmpty) {
        final idx = filteredBlocks.indexWhere(
          (b) => targets.contains(b['id']?.toString()),
        );
        if (idx >= 0) anchor = idx;
      }
      final start = (anchor - _excerptRadius).clamp(0, filteredBlocks.length);
      final end =
          (anchor + _excerptRadius + 1).clamp(0, filteredBlocks.length);
      final windowed = filteredBlocks.sublist(start, end);

      for (final b in windowed) {
        final id = b['id']?.toString();
        if (id != null) {
          _blockKeys[id] = GlobalKey();
        }
      }

      setState(() {
        _blocks = windowed;
        _moreBefore = start > 0;
        _moreAfter = end < filteredBlocks.length;
        _loading = false;
      });

      if (widget.highlightBlockIds != null && widget.highlightBlockIds!.isNotEmpty) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _scrollToTargetBlock();
        });
      }
    } catch (e) {
      setState(() {
        _error = 'Failed to load content: $e';
        _loading = false;
      });
    }
  }

  void _scrollToTargetBlock() {
    if (_hasScrolled) return;
    for (final targetId in widget.highlightBlockIds!) {
      final key = _blockKeys[targetId];
      if (key != null && key.currentContext != null) {
        Scrollable.ensureVisible(
          key.currentContext!,
          duration: const Duration(milliseconds: 300),
          alignment: 0.1,
        );
        setState(() {
          _hasScrolled = true;
        });
        break;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
      ),
      body: _buildBody(theme),
    );
  }

  Widget _buildBody(ThemeData theme) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Text(
            _error!,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyLarge?.copyWith(color: AppColors.error),
          ),
        ),
      );
    }
    if (_blocks.isEmpty) {
      return const Center(child: Text('This book is empty.'));
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      // Purchase/study notices bracket the excerpt.
      itemCount: _blocks.length + 2,
      itemBuilder: (context, rawIndex) {
        if (rawIndex == 0) {
          return _buildExcerptNotice(theme, top: true);
        }
        if (rawIndex == _blocks.length + 1) {
          return _buildExcerptNotice(theme, top: false);
        }
        final index = rawIndex - 1;
        final block = _blocks[index] as Map<String, dynamic>;
        final id = block['id']?.toString() ?? '';
        final type = block['type']?.toString() ?? 'paragraph';
        final text = block['text']?.toString() ?? '';
        final printedPage = block['printed_page'];
        
        final isHighlighted = widget.highlightBlockIds?.contains(id) ?? false;
        
        // Detect page transitions
        Widget? pageMarker;
        if (printedPage != null && index > 0) {
          final prevBlock = _blocks[index - 1] as Map<String, dynamic>;
          if (prevBlock['printed_page'] != printedPage) {
            pageMarker = _buildPageMarker(theme, printedPage.toString());
          }
        } else if (printedPage != null && index == 0) {
          pageMarker = _buildPageMarker(theme, printedPage.toString());
        }

        Widget blockWidget = _buildBlockWidget(theme, id, type, text, isHighlighted);
        
        if (pageMarker != null) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              pageMarker,
              blockWidget,
            ],
          );
        }
        return blockWidget;
      },
    );
  }

  Widget _buildExcerptNotice(ThemeData theme, {required bool top}) {
    final truncated = top ? _moreBefore : _moreAfter;
    return Container(
      margin: EdgeInsets.only(
        top: top ? 0 : AppSpacing.xl,
        bottom: top ? AppSpacing.xl : AppSpacing.xxl,
      ),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.gold.withValues(alpha: 0.08),
        border: Border.all(color: AppColors.gold.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(AppSpacing.radius),
      ),
      child: Column(
        children: [
          Text(
            truncated
                ? 'Study excerpt — the rest of this book is not shown.'
                : 'Study excerpt',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            'This app is a study aide. Please purchase the full book at your '
            'local meeting, intergroup office, or from the publisher.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.textTheme.bodySmall?.color?.withValues(alpha: 0.8),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPageMarker(ThemeData theme, String pageNum) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
      padding: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(color: theme.dividerColor, width: 0.5, style: BorderStyle.solid),
          bottom: BorderSide(color: theme.dividerColor, width: 0.5, style: BorderStyle.solid),
        ),
      ),
      child: Text(
        'Page $pageNum',
        textAlign: TextAlign.center,
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.textTheme.bodySmall?.color?.withValues(alpha: 0.6),
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  Widget _buildBlockWidget(
    ThemeData theme,
    String id,
    String type,
    String text,
    bool isHighlighted,
  ) {
    TextStyle? style;
    EdgeInsets padding = const EdgeInsets.symmetric(vertical: 4);
    
    switch (type) {
      case 'heading':
        style = theme.textTheme.titleMedium?.copyWith(
          fontWeight: FontWeight.w700,
          color: AppColors.accent,
        );
        padding = const EdgeInsets.only(top: AppSpacing.md, bottom: AppSpacing.sm);
      case 'epigraph':
        style = theme.textTheme.bodyMedium?.copyWith(
          fontStyle: FontStyle.italic,
          color: theme.textTheme.bodyMedium?.color?.withValues(alpha: 0.8),
        );
        padding = const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.sm);
      case 'footnote':
        style = theme.textTheme.bodySmall?.copyWith(
          color: theme.textTheme.bodySmall?.color?.withValues(alpha: 0.7),
        );
        padding = const EdgeInsets.symmetric(vertical: 2);
      case 'list':
        style = theme.textTheme.bodyMedium;
        padding = const EdgeInsets.only(left: AppSpacing.md, top: 2, bottom: 2);
      default:
        style = theme.textTheme.bodyMedium;
    }

    Widget content = Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
      child: Text(
        type == 'list' ? '• $text' : text,
        style: style,
      ),
    );

    if (isHighlighted) {
      final isDark = theme.brightness == Brightness.dark;
      final hlBg = AppColors.highlightBg(isDark);
      // Force contrasting text color so highlighting is always readable
      // regardless of the block type (heading, footnote, etc.).
      final hlTextColor = isDark ? Colors.white : AppColors.lightText;
      content = Container(
        decoration: BoxDecoration(
          color: hlBg,
          borderRadius: BorderRadius.circular(4),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Text(
          type == 'list' ? '• $text' : text,
          style: style?.copyWith(color: hlTextColor),
        ),
      );
    }

    return Container(
      key: _blockKeys[id],
      padding: padding,
      child: content,
    );
  }
}
