import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

class GraphNode {
  final String id;
  final String label;
  final String type;
  final String category;
  final String? source;
  final String? excerpt;
  Offset position;

  GraphNode({
    required this.id,
    required this.label,
    required this.type,
    required this.category,
    this.source,
    this.excerpt,
    this.position = Offset.zero,
  });
}

class GraphEdge {
  final String source;
  final String target;
  final String label;

  GraphEdge({
    required this.source,
    required this.target,
    required this.label,
  });
}

class RagGraphScreen extends ConsumerStatefulWidget {
  final String initialQuery;
  final void Function(String prompt)? onSelectPrompt;

  const RagGraphScreen({
    super.key,
    this.initialQuery = 'The Twelve Steps',
    this.onSelectPrompt,
  });

  @override
  ConsumerState<RagGraphScreen> createState() => _RagGraphScreenState();
}

class _RagGraphScreenState extends ConsumerState<RagGraphScreen> {
  late final TextEditingController _searchController;
  final TransformationController _transformationController = TransformationController();

  bool _loading = false;
  final Map<String, GraphNode> _nodeMap = {};
  final List<GraphEdge> _edges = [];
  GraphNode? _selectedNode;

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController(text: widget.initialQuery);
    _fetchFocusedGraph(widget.initialQuery);
  }

  @override
  void dispose() {
    _searchController.dispose();
    _transformationController.dispose();
    super.dispose();
  }

  /// Fetches graph data and replaces screen state to display ONLY the focused node
  /// and its direct relationships with zero overlaps.
  Future<void> _fetchFocusedGraph(String query, {GraphNode? tappedNode}) async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      if (tappedNode != null) {
        _selectedNode = tappedNode;
      }
    });

    final config = ref.read(appConfigProvider);
    final uri = Uri.parse('${config.baseUrl}/api/graph?q=${Uri.encodeComponent(query)}');

    try {
      final resp = await http.get(uri).timeout(const Duration(seconds: 10));
      if (resp.statusCode == 200) {
        final data = json.decode(resp.body) as Map<String, dynamic>;
        final rawNodes = data['nodes'] as List? ?? [];
        final rawEdges = data['edges'] as List? ?? [];

        _nodeMap.clear();
        _edges.clear();

        final center = const Offset(800, 600);
        final rng = Random();

        // 1. Separate nodes by role/type
        final centralNodes = <GraphNode>[];
        final passageNodes = <GraphNode>[];
        final termNodes = <GraphNode>[];
        final otherNodes = <GraphNode>[];

        for (var i = 0; i < rawNodes.length; i++) {
          final item = rawNodes[i] as Map<String, dynamic>;
          final id = item['id'] as String? ?? 'n_${rng.nextInt(100000)}';
          final label = item['label'] as String? ?? '';
          final type = item['type'] as String? ?? 'node';
          final cat = item['category'] as String? ?? 'general';
          final src = item['source'] as String?;
          final exc = item['excerpt'] as String?;

          final node = GraphNode(
            id: id,
            label: label,
            type: type,
            category: cat,
            source: src,
            excerpt: exc,
          );

          if (type == 'query' || id == 'central_query') {
            centralNodes.add(node);
          } else if (type == 'passage') {
            passageNodes.add(node);
          } else if (type == 'term') {
            termNodes.add(node);
          } else {
            otherNodes.add(node);
          }
        }

        // Place central query node at (800, 600)
        for (final cn in centralNodes) {
          cn.position = center;
          _nodeMap[cn.id] = cn;
        }

        // Inner Ring: Terms & Steps (Radius: 220px)
        final innerRing = [...termNodes, ...otherNodes];
        for (var i = 0; i < innerRing.length; i++) {
          final angle = (2 * pi * i) / max(innerRing.length, 1);
          final radius = 220.0;
          innerRing[i].position = Offset(
            center.dx + cos(angle) * radius,
            center.dy + sin(angle) * radius,
          );
          _nodeMap[innerRing[i].id] = innerRing[i];
        }

        // Outer Ring: Passages & Literature Sources (Radius: 400px)
        for (var i = 0; i < passageNodes.length; i++) {
          final angle = (2 * pi * i) / max(passageNodes.length, 1) + (pi / max(passageNodes.length, 1));
          final radius = 400.0;
          passageNodes[i].position = Offset(
            center.dx + cos(angle) * radius,
            center.dy + sin(angle) * radius,
          );
          _nodeMap[passageNodes[i].id] = passageNodes[i];
        }

        // Anti-collision pass: push apart any nodes closer than 140px
        final allPlacedNodes = _nodeMap.values.toList();
        for (var iteration = 0; iteration < 5; iteration++) {
          for (var i = 0; i < allPlacedNodes.length; i++) {
            for (var j = i + 1; j < allPlacedNodes.length; j++) {
              final n1 = allPlacedNodes[i];
              final n2 = allPlacedNodes[j];
              if (n1.type == 'query' || n2.type == 'query') continue;

              final delta = n2.position - n1.position;
              final dist = delta.distance;
              const minDist = 140.0;
              if (dist < minDist && dist > 0) {
                final overlap = (minDist - dist) / 2.0;
                final norm = delta / dist;
                n1.position -= norm * overlap;
                n2.position += norm * overlap;
              }
            }
          }
        }

        // Add edges
        for (final item in rawEdges) {
          final eMap = item as Map<String, dynamic>;
          final s = eMap['source'] as String? ?? '';
          final t = eMap['target'] as String? ?? '';
          if (s.isNotEmpty && t.isNotEmpty && _nodeMap.containsKey(s) && _nodeMap.containsKey(t)) {
            _edges.add(GraphEdge(source: s, target: t, label: eMap['label'] as String? ?? ''));
          }
        }

        if (tappedNode != null && _nodeMap.containsKey(tappedNode.id)) {
          _selectedNode = _nodeMap[tappedNode.id];
        } else if (_nodeMap.isNotEmpty) {
          _selectedNode = _nodeMap.values.first;
        }

        if (mounted) {
          setState(() {
            _loading = false;
          });
        }
        return;
      }
    } catch (_) {}

    if (mounted) setState(() => _loading = false);
  }

  void _onNodeTap(GraphNode node) {
    setState(() => _selectedNode = node);

    // Extract search query term from node
    String targetQuery = node.label;
    if (node.type == 'passage') {
      targetQuery = node.source ?? node.label.split(':').first;
    } else if (node.type == 'prompt') {
      targetQuery = node.label.replaceAll(RegExp(r'^(How do I apply|What does the|What does|say about|teach about|\?)'), '').trim();
    }

    _searchController.text = targetQuery;
    _fetchFocusedGraph(targetQuery, tappedNode: node);
  }

  void _resetZoom() {
    _transformationController.value = Matrix4.identity();
  }

  void _zoomBy(double factor) {
    final matrix = _transformationController.value.clone();
    matrix.scale(factor, factor, 1.0);
    _transformationController.value = matrix;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isLight = theme.brightness == Brightness.light;
    final nodeList = _nodeMap.values.toList();

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const Icon(Icons.bubble_chart, color: AppColors.accent, size: 22),
            const SizedBox(width: AppSpacing.sm),
            const Text('Knowledge Graph'),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Reset Graph',
            onPressed: () {
              _searchController.text = 'The Twelve Steps';
              _fetchFocusedGraph('The Twelve Steps');
            },
          ),
        ],
      ),
      body: Column(
        children: [
          // Search & Navigation Bar
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    decoration: InputDecoration(
                      hintText: 'Search steps, literature, or concepts (e.g. The Twelve Steps)...',
                      prefixIcon: const Icon(Icons.search),
                      suffixIcon: IconButton(
                        icon: const Icon(Icons.arrow_forward),
                        onPressed: () => _fetchFocusedGraph(_searchController.text),
                      ),
                    ),
                    onSubmitted: (q) => _fetchFocusedGraph(q),
                  ),
                ),
              ],
            ),
          ),

          // Interactive Graph Canvas with Smooth Pinch-to-Zoom & Zero Collisions
          Expanded(
            child: Stack(
              children: [
                InteractiveViewer(
                  transformationController: _transformationController,
                  boundaryMargin: const EdgeInsets.all(2500),
                  minScale: 0.1,
                  maxScale: 4.0,
                  clipBehavior: Clip.none,
                  child: SizedBox(
                    width: 1600,
                    height: 1200,
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        // Graph Edges Painter
                        CustomPaint(
                          size: const Size(1600, 1200),
                          painter: _GraphPainter(
                            nodes: nodeList,
                            edges: _edges,
                            selectedNodeId: _selectedNode?.id,
                            theme: theme,
                          ),
                        ),

                        // Interactive Non-Overlapping Nodes
                        for (final node in nodeList)
                          Positioned(
                            left: node.position.dx - 65,
                            top: node.position.dy - 28,
                            child: GestureDetector(
                              onTap: () => _onNodeTap(node),
                              child: AnimatedContainer(
                                duration: const Duration(milliseconds: 200),
                                width: 130,
                                padding: const EdgeInsets.all(AppSpacing.xs),
                                decoration: BoxDecoration(
                                  color: _nodeColor(node.type, theme),
                                  borderRadius: BorderRadius.circular(AppSpacing.radius),
                                  border: Border.all(
                                    color: _selectedNode?.id == node.id
                                        ? AppColors.accent
                                        : (isLight ? Colors.black26 : Colors.white30),
                                    width: _selectedNode?.id == node.id ? 2.5 : 1.0,
                                  ),
                                  boxShadow: [
                                    BoxShadow(
                                      color: _selectedNode?.id == node.id
                                          ? AppColors.accent.withValues(alpha: 0.5)
                                          : Colors.black26,
                                      blurRadius: _selectedNode?.id == node.id ? 8 : 4,
                                    ),
                                  ],
                                ),
                                child: Row(
                                  children: [
                                    Icon(_nodeIcon(node.type), size: 14, color: Colors.white),
                                    const SizedBox(width: 4),
                                    Expanded(
                                      child: Text(
                                        node.label,
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                        style: theme.textTheme.bodySmall?.copyWith(
                                          fontSize: 10,
                                          color: Colors.white,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),

                if (_loading)
                  const Positioned(
                    top: 16,
                    right: 16,
                    child: SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2.5),
                    ),
                  ),

                // Floating Zoom Controls
                Positioned(
                  right: 16,
                  bottom: 16,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      FloatingActionButton.small(
                        heroTag: 'zoom_in',
                        onPressed: () => _zoomBy(1.25),
                        child: const Icon(Icons.add),
                      ),
                      const SizedBox(height: 6),
                      FloatingActionButton.small(
                        heroTag: 'zoom_out',
                        onPressed: () => _zoomBy(0.8),
                        child: const Icon(Icons.remove),
                      ),
                      const SizedBox(height: 6),
                      FloatingActionButton.small(
                        heroTag: 'zoom_reset',
                        onPressed: _resetZoom,
                        child: const Icon(Icons.center_focus_strong),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          // Selected Node Detail Panel
          if (_selectedNode != null)
            Container(
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest,
                border: Border(top: BorderSide(color: isLight ? theme.colorScheme.outlineVariant : Colors.white12)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: _nodeColor(_selectedNode!.type, theme),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                _selectedNode!.type.toUpperCase(),
                                style: const TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.white),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _selectedNode!.label,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold),
                              ),
                            ),
                          ],
                        ),
                        if (_selectedNode!.excerpt != null) ...[
                          const SizedBox(height: 4),
                          Text(
                            '"${_selectedNode!.excerpt}"',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodySmall?.copyWith(
                              fontStyle: FontStyle.italic,
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  ElevatedButton.icon(
                    icon: const Icon(Icons.auto_awesome, size: 16),
                    label: const Text('Study This'),
                    onPressed: () {
                      if (widget.onSelectPrompt != null) {
                        final text = _selectedNode!.type == 'passage'
                            ? 'Tell me more about what ${_selectedNode!.source ?? _selectedNode!.label} says here: ${_selectedNode!.excerpt ?? ''}'
                            : _selectedNode!.label;
                        widget.onSelectPrompt!(text);
                      }
                      Navigator.of(context).pop();
                    },
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Color _nodeColor(String type, ThemeData theme) {
    switch (type) {
      case 'query':
        return AppColors.brand;
      case 'step':
        return AppColors.gold;
      case 'passage':
        return const Color(0xFF1E3A8A);
      case 'term':
        return const Color(0xFF0D9488);
      case 'prompt':
        return AppColors.accent;
      default:
        return theme.colorScheme.surface;
    }
  }

  IconData _nodeIcon(String type) {
    switch (type) {
      case 'query':
        return Icons.hub;
      case 'step':
        return Icons.stars;
      case 'passage':
        return Icons.menu_book;
      case 'term':
        return Icons.local_offer;
      case 'prompt':
        return Icons.lightbulb_outline;
      default:
        return Icons.circle;
    }
  }
}

class _GraphPainter extends CustomPainter {
  final List<GraphNode> nodes;
  final List<GraphEdge> edges;
  final String? selectedNodeId;
  final ThemeData theme;

  _GraphPainter({
    required this.nodes,
    required this.edges,
    this.selectedNodeId,
    required this.theme,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final nodeMap = {for (final n in nodes) n.id: n};

    final isLight = theme.brightness == Brightness.light;
    final normalPaint = Paint()
      ..color = isLight
          ? AppColors.brand.withValues(alpha: 0.3)
          : AppColors.accent.withValues(alpha: 0.35)
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;

    final highlightPaint = Paint()
      ..color = AppColors.accent
      ..strokeWidth = 2.5
      ..style = PaintingStyle.stroke;

    for (final edge in edges) {
      final src = nodeMap[edge.source];
      final tgt = nodeMap[edge.target];
      if (src != null && tgt != null) {
        final isHighlighted = selectedNodeId != null && (src.id == selectedNodeId || tgt.id == selectedNodeId);
        canvas.drawLine(src.position, tgt.position, isHighlighted ? highlightPaint : normalPaint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _GraphPainter oldDelegate) => true;
}
