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
  bool _loading = true;
  String? _error;
  List<dynamic> _blocks = [];
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

      for (final b in filteredBlocks) {
        final id = b['id']?.toString();
        if (id != null) {
          _blockKeys[id] = GlobalKey();
        }
      }

      setState(() {
        _blocks = filteredBlocks;
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
      itemCount: _blocks.length,
      itemBuilder: (context, index) {
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
      final highlightColor = theme.brightness == Brightness.dark
          ? const Color(0xFF1F4A3E)
          : const Color(0xFFD4F5E9);
      content = Container(
        decoration: BoxDecoration(
          color: highlightColor,
          borderRadius: BorderRadius.circular(4),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Text(
          type == 'list' ? '• $text' : text,
          style: style,
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
