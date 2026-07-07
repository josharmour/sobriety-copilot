import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/data/repositories/library_repository.dart';
import 'package:sobriety_copilot_mobile/features/library/offline_reader.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

class LibrarySheet extends ConsumerStatefulWidget {
  const LibrarySheet({super.key});

  @override
  ConsumerState<LibrarySheet> createState() => _LibrarySheetState();
}

class _LibrarySheetState extends ConsumerState<LibrarySheet> {
  bool _checking = true;
  bool _installed = false;
  bool _downloading = false;
  double _downloadProgress = 0.0;
  String? _statusMessage;
  
  int? _serverVersion;
  String? _serverSha256;
  int? _serverDocCount;

  List<OfflineBookIndex> _books = [];
  List<OfflineSearchResult> _searchResults = [];
  final TextEditingController _searchController = TextEditingController();
  bool _searching = false;

  @override
  void initState() {
    super.initState();
    _initLibraryState();
  }

  Future<void> _initLibraryState() async {
    final repo = ref.read(libraryRepositoryProvider);
    final isInstalled = await repo.isPackInstalled;
    setState(() {
      _installed = isInstalled;
      _checking = true;
    });

    if (isInstalled) {
      final list = await repo.getBooks();
      setState(() {
        _books = list;
      });
    }

    // Check for server updates
    try {
      final info = await repo.checkLatestPack();
      if (info != null && info.containsKey('pack_version')) {
        setState(() {
          _serverVersion = info['pack_version'] as int?;
          _serverSha256 = info['sha256']?.toString();
          _serverDocCount = info['doc_count'] as int?;
        });
      }
    } catch (_) {}

    setState(() {
      _checking = false;
    });
  }

  Future<void> _startDownload() async {
    if (_serverVersion == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not fetch update info from server.')),
      );
      return;
    }

    setState(() {
      _downloading = true;
      _downloadProgress = 0.0;
      _statusMessage = 'Downloading offline pack (~40MB)...';
    });

    try {
      final repo = ref.read(libraryRepositoryProvider);
      await repo.downloadAndInstallPack(
        _serverVersion!,
        _serverSha256 ?? '',
        onProgress: (p) {
          setState(() {
            _downloadProgress = p;
            if (p >= 1.0) {
              _statusMessage = 'Extracting documents...';
            }
          });
        },
      );
      
      final booksList = await repo.getBooks();
      setState(() {
        _installed = true;
        _downloading = false;
        _books = booksList;
      });
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Offline library installed successfully!')),
        );
      }
    } catch (e) {
      setState(() {
        _downloading = false;
        _statusMessage = null;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Download failed: $e')),
        );
      }
    }
  }

  Future<void> _performSearch(String query) async {
    final q = query.trim();
    if (q.length < 2) {
      setState(() {
        _searchResults = [];
        _searching = false;
      });
      return;
    }

    setState(() {
      _searching = true;
    });

    final repo = ref.read(libraryRepositoryProvider);
    final results = await repo.search(q);
    
    setState(() {
      _searchResults = results;
      _searching = false;
    });
  }

  String _getBookTitle(String docId) {
    final b = _books.firstWhere(
      (x) => x.docId == docId,
      orElse: () => OfflineBookIndex(docId: '', title: docId, author: '', category: '', blocksCount: 0),
    );
    return b.title;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final height = MediaQuery.of(context).size.height * 0.85;

    return Container(
      height: height,
      decoration: BoxDecoration(
        color: theme.scaffoldBackgroundColor,
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(AppSpacing.radius),
          topRight: Radius.circular(AppSpacing.radius),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Recovery Library',
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    fontSize: AppTypography.title,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
          ),
          
          const Divider(),

          Expanded(
            child: _buildContent(theme),
          ),
        ],
      ),
    );
  }

  Widget _buildContent(ThemeData theme) {
    if (_downloading) {
      return Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.download_for_offline, size: 64, color: AppColors.accent),
            const SizedBox(height: AppSpacing.md),
            Text(
              _statusMessage ?? 'Preparing...',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyLarge,
            ),
            const SizedBox(height: AppSpacing.lg),
            LinearProgressIndicator(
              value: _downloadProgress > 0 ? _downloadProgress : null,
              backgroundColor: theme.dividerColor,
              color: AppColors.accent,
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              '${(_downloadProgress * 100).toStringAsFixed(0)}%',
              style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.bold),
            ),
          ],
        ),
      );
    }

    if (!_installed) {
      return Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.library_books_outlined, size: 64, color: AppColors.accent),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Library Offline Access',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              'You can download the full literature package to search, read, and browse fully offline.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.textTheme.bodySmall?.color,
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
            if (_checking)
              const CircularProgressIndicator()
            else if (_serverVersion != null)
              ElevatedButton.icon(
                icon: const Icon(Icons.download),
                label: Text('Download Library (${_serverDocCount ?? 0} books, ~44MB)'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
                ),
                onPressed: _startDownload,
              )
            else
              Text(
                'Server offline or update information unavailable right now.',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium?.copyWith(color: AppColors.error),
              ),
          ],
        ),
      );
    }

    // Installed - show search and book list
    final repo = ref.read(libraryRepositoryProvider);
    final showUpdateBanner = _serverVersion != null && _serverVersion! > repo.localPackVersion;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (showUpdateBanner)
          Container(
            color: AppColors.accent.withValues(alpha: 0.1),
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Row(
              children: [
                const Icon(Icons.info_outline, color: AppColors.accent),
                const SizedBox(width: AppSpacing.md),
                const Expanded(
                  child: Text('An updated version of the literature library is available.'),
                ),
                TextButton(
                  onPressed: _startDownload,
                  child: const Text('Update'),
                ),
              ],
            ),
          ),
          
        // Search input
        Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: SearchBar(
            controller: _searchController,
            hintText: 'Search offline literature...',
            leading: const Icon(Icons.search),
            trailing: _searchController.text.isNotEmpty
                ? [
                    IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _searchController.clear();
                        _performSearch('');
                      },
                    )
                  ]
                : null,
            onChanged: _performSearch,
          ),
        ),

        Expanded(
          child: _searchController.text.length >= 2 ? _buildSearchResults(theme) : _buildBooksList(theme),
        ),
      ],
    );
  }

  Widget _buildSearchResults(ThemeData theme) {
    if (_searching) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_searchResults.isEmpty) {
      return const Center(child: Text('No matching passages found.'));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: _searchResults.length,
      itemBuilder: (context, index) {
        final res = _searchResults[index];
        final title = _getBookTitle(res.docId);
        
        return Card(
          margin: const EdgeInsets.only(bottom: AppSpacing.md),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppSpacing.radius),
            onTap: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => OfflineReaderScreen(
                    docId: res.docId,
                    title: title,
                    highlightBlockIds: [res.blockId],
                  ),
                ),
              );
            },
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: AppColors.accent,
                    ),
                  ),
                  if (res.heading.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      res.heading,
                      style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.bold),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Text(
                    res.text,
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodyMedium,
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildBooksList(ThemeData theme) {
    if (_books.isEmpty) {
      return const Center(child: Text('No books in library.'));
    }

    // Group books by category
    final Map<String, List<OfflineBookIndex>> categories = {};
    for (final b in _books) {
      final cat = b.category.replaceAll(RegExp(r'[_-]+'), ' ').replaceFirstMapped(
        RegExp(r'\b\w'), (m) => m[0]!.toUpperCase()
      );
      categories.putIfAbsent(cat, () => []).add(b);
    }

    final catNames = categories.keys.toList()..sort();

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: catNames.length,
      itemBuilder: (context, index) {
        final cat = catNames[index];
        final list = categories[cat]!;
        
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Text(
                cat,
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: theme.brightness == Brightness.dark
                      ? AppColors.accent
                      : AppColors.brand,
                ),
              ),
            ),
            ...list.map((b) => ListTile(
              title: Text(b.title),
              subtitle: Text('${b.author} · ${b.blocksCount} sections'),
              leading: const Icon(Icons.book_outlined),
              trailing: const Icon(Icons.chevron_right),
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => OfflineReaderScreen(
                      docId: b.docId,
                      title: b.title,
                    ),
                  ),
                );
              },
            )),
            const SizedBox(height: AppSpacing.md),
          ],
        );
      },
    );
  }
}
