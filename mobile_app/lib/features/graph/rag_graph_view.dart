/// Knowledge Graph — a visual way through the recovery library.
///
/// The screen has three layers:
///
/// 1. **Canvas** (top): a zoomable map. In *overview* it shows every topic in
///    the taxonomy, clustered by theme and linked by how often topics occur in
///    the same passage. Focusing a *topic* rearranges the map into rings — the
///    topics it leads to, then the books that discuss it. Focusing a *book*
///    puts the book in the middle with its topics around it. Transitions
///    animate so you keep your bearings.
/// 2. **Panel** (bottom sheet): what is at the focused node — passages with
///    chapter and page, chapters of a book, search results. Every passage
///    lists the other topics it touches, so you can hop topic → passage →
///    topic through the literature.
/// 3. **Trail** (under the search box): where you have been; tap to go back.
///
/// Data comes from `/api/graph/*` (see `src/rag/graph.py`).
library;

import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

import 'graph_api.dart';
import 'graph_layout.dart';
import 'graph_models.dart';
import 'graph_painter.dart';
import 'graph_panels.dart';
import 'passage_reader.dart';

const double _kCanvas = 1600;
const Offset _kCenter = Offset(_kCanvas / 2, _kCanvas / 2);

enum _Mode { overview, topic, book, search }

class _TrailEntry {
  final _Mode mode;
  final String id;
  final String label;
  final Color color;
  final String? bookId;
  const _TrailEntry(this.mode, this.id, this.label, this.color, {this.bookId});
}

class _PassagesView {
  final PassagePage page;
  final List<Passage> loaded;
  final String? sectionTitle;
  final int? section;
  final bool loadingMore;
  const _PassagesView({
    required this.page,
    required this.loaded,
    this.sectionTitle,
    this.section,
    this.loadingMore = false,
  });
  _PassagesView copyWith({PassagePage? page, List<Passage>? loaded, bool? loadingMore}) => _PassagesView(
        page: page ?? this.page,
        loaded: loaded ?? this.loaded,
        sectionTitle: sectionTitle,
        section: section,
        loadingMore: loadingMore ?? this.loadingMore,
      );
}

class RagGraphScreen extends ConsumerStatefulWidget {
  final String initialQuery;
  final void Function(String prompt)? onSelectPrompt;

  const RagGraphScreen({super.key, this.initialQuery = '', this.onSelectPrompt});

  @override
  ConsumerState<RagGraphScreen> createState() => _RagGraphScreenState();
}

class _RagGraphScreenState extends ConsumerState<RagGraphScreen> with SingleTickerProviderStateMixin {
  late final GraphApi _api;
  late final TextEditingController _search;
  final FocusNode _searchFocus = FocusNode();
  final TransformationController _tc = TransformationController();
  final DraggableScrollableController _panel = DraggableScrollableController();
  final ScrollController _trailScroll = ScrollController();
  late final AnimationController _anim;

  // Map
  GraphMap? _map;
  String? _mapError;
  GraphBuilding? _building;
  Timer? _pollTimer;
  GraphLayout? _overviewLayout;

  // Mode & panel content
  _Mode _mode = _Mode.overview;
  TopicDetail? _topic;
  BookDetail? _book;
  GraphSearchResult? _searchResult;
  _PassagesView? _passages;
  String? _panelBook; // a book to surface first inside a topic
  bool _panelLoading = false;
  String? _panelError;
  int _requestSeq = 0;

  // Canvas
  GraphLayout _layout = const GraphLayout(nodes: {}, edges: [], positions: {});
  Map<String, Offset> _from = {};
  Map<String, Offset> _to = {};
  Map<String, Offset> _shown = {};
  Matrix4? _matFrom;
  Matrix4? _matTo;
  String? _selectedId;
  String? _hoveredId;
  Set<String> _highlight = {};
  String? _groupFilter;
  Size _viewport = Size.zero;
  double _zoom = 1;
  final List<_TrailEntry> _trail = [];
  List<TopicNode> _suggestions = const [];

  @override
  void initState() {
    super.initState();
    _api = GraphApi(ref.read(appConfigProvider).baseUrl);
    _search = TextEditingController(text: widget.initialQuery);
    _anim = AnimationController(vsync: this, duration: const Duration(milliseconds: 520))
      ..addListener(_onAnimTick);
    _tc.addListener(_onTransform);
    _loadMap();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _anim.dispose();
    _tc.removeListener(_onTransform);
    _tc.dispose();
    _search.dispose();
    _searchFocus.dispose();
    _panel.dispose();
    _trailScroll.dispose();
    super.dispose();
  }

  // ── Loading ────────────────────────────────────────────────────────────────

  Future<void> _loadMap() async {
    _pollTimer?.cancel();
    setState(() {
      _mapError = null;
    });
    try {
      final m = await _api.map();
      if (!mounted) return;
      _building = null;
      _map = m;
      _overviewLayout = _buildOverview(m);
      _showOverview(animate: false);
      if (widget.initialQuery.trim().isNotEmpty) {
        _runSearch(widget.initialQuery.trim());
      }
    } on GraphBuilding catch (b) {
      if (!mounted) return;
      setState(() => _building = b);
      _pollTimer = Timer(const Duration(milliseconds: 2500), _loadMap);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _building = null;
        _mapError = 'Could not reach the server. $e';
      });
    }
  }

  // ── Layouts ────────────────────────────────────────────────────────────────

  double _topicRadius(TopicNode t, int maxMentions) => 9 + 13 * sqrt(t.mentions / max(maxMentions, 1));

  GraphLayout _buildOverview(GraphMap m) {
    final maxMentions = m.topics.fold<int>(1, (a, t) => max(a, t.mentions));
    final nodes = [
      for (final t in m.topics)
        LayoutNode(id: t.id, kind: 'topic', label: t.label, group: t.group, radius: _topicRadius(t, maxMentions)),
    ];
    final maxW = m.topicEdges.fold<double>(0.01, (a, e) => max(a, e.weight));
    final edges = [for (final e in m.topicEdges) LayoutEdge(e.source, e.target, e.weight / maxW)];
    final laid = forceLayout(nodes: nodes, edges: edges, groupOrder: m.groups.map((g) => g.id).toList());
    // Centre the cloud on the canvas.
    final b = laid.bounds;
    final shift = _kCenter - b.center;
    return GraphLayout(
      nodes: laid.nodes,
      edges: laid.edges,
      positions: {for (final e in laid.positions.entries) e.key: e.value + shift},
    );
  }

  GraphLayout _applyOverviewEmphasis(GraphLayout base) {
    final filter = _groupFilter;
    final matched = _mode == _Mode.search ? _searchTopicIds() : null;
    if (filter == null && matched == null) return base;
    return GraphLayout(
      nodes: {
        for (final n in base.nodes.values)
          n.id: n.copyWith(dimmed: (filter != null && n.group != filter) || (matched != null && !matched.contains(n.id))),
      },
      edges: base.edges,
      positions: base.positions,
    );
  }

  Set<String> _searchTopicIds() => {
        if (_searchResult != null) ...[
          ..._searchResult!.topics.map((t) => t.id),
          ..._searchResult!.suggestedTopics.map((t) => t.id),
        ],
      };

  GraphLayout _buildTopicLayout(TopicDetail d) {
    final m = _map!;
    final maxMentions = m.topics.fold<int>(1, (a, t) => max(a, t.mentions));
    final focus = LayoutNode(
      id: d.topic.id,
      kind: 'topic',
      label: d.topic.label,
      group: d.topic.group,
      radius: 30,
      isFocus: true,
    );
    final maxW = d.related.fold<double>(0.01, (a, t) => max(a, t.weight));
    final ring1 = [
      for (final r in d.related)
        LayoutNode(
          id: r.id,
          kind: 'topic',
          label: r.label,
          group: r.group,
          radius: max(11.0, _topicRadius(r, maxMentions) * 0.9),
          weight: r.weight / maxW,
        ),
    ];
    final maxC = d.books.fold<int>(1, (a, b) => max(a, b.count));
    final ring2 = [
      for (final b in d.books.take(14))
        LayoutNode(
          id: 'book:${b.id}',
          kind: 'book',
          label: b.title,
          group: b.category,
          radius: 28,
          weight: b.count / maxC,
        ),
    ];
    final edges = [
      for (final r in ring1) LayoutEdge(focus.id, r.id, r.weight),
      for (final b in ring2) LayoutEdge(focus.id, b.id, 0.25 + 0.75 * b.weight),
    ];
    return radialLayout(focus: focus, ring1: ring1, ring2: ring2, edges: edges, center: _kCenter);
  }

  GraphLayout _buildBookLayout(BookDetail d) {
    final focus = LayoutNode(
      id: 'book:${d.book.id}',
      kind: 'book',
      label: d.book.title,
      group: d.book.category,
      radius: 40,
      weight: 1,
      isFocus: true,
    );
    final maxD = d.topics.fold<double>(0.01, (a, t) => max(a, t.density));
    final ring1 = [
      for (final t in d.topics.take(18))
        LayoutNode(
          id: t.id,
          kind: 'topic',
          label: t.label,
          group: t.group,
          radius: 11 + 12 * sqrt(t.density / maxD),
          weight: t.density / maxD,
        ),
    ];
    final edges = [for (final t in ring1) LayoutEdge(focus.id, t.id, t.weight)];
    return radialLayout(focus: focus, ring1: ring1, ring2: const [], edges: edges, innerRadius: 330, center: _kCenter);
  }

  // ── Animation ──────────────────────────────────────────────────────────────

  void _setLayout(GraphLayout layout, {bool animate = true, String? emergeFrom}) {
    final origin = (emergeFrom != null ? _shown[emergeFrom] : null) ?? _shown[_selectedId] ?? _kCenter;
    _from = {for (final id in layout.positions.keys) id: _shown[id] ?? origin};
    _to = Map.of(layout.positions);
    _layout = layout;
    _matFrom = _tc.value.clone();
    _matTo = _fitMatrix(layout);
    if (!animate || _viewport == Size.zero) {
      _shown = Map.of(_to);
      if (_matTo != null) _tc.value = _matTo!;
      _anim.value = 1;
      setState(() {});
      return;
    }
    _anim.forward(from: 0);
  }

  void _onAnimTick() {
    final t = Curves.easeInOutCubic.transform(_anim.value);
    _shown = {for (final e in _to.entries) e.key: Offset.lerp(_from[e.key] ?? e.value, e.value, t)!};
    if (_matFrom != null && _matTo != null) {
      _tc.value = Matrix4Tween(begin: _matFrom, end: _matTo).lerp(t);
    }
    setState(() {});
  }

  void _onTransform() {
    final z = _tc.value.getMaxScaleOnAxis();
    if ((z - _zoom).abs() > 0.02) setState(() => _zoom = z);
  }

  /// Matrix that fits [layout] into the part of the viewport above the panel.
  Matrix4? _fitMatrix(GraphLayout layout) {
    if (_viewport == Size.zero || layout.positions.isEmpty) return null;
    final b = layout.bounds;
    final visibleH = _viewport.height * 0.60;
    final scale = min(min(_viewport.width / b.width, visibleH / b.height), 1.4).clamp(0.12, 1.4);
    final dx = _viewport.width / 2 - b.center.dx * scale;
    final dy = visibleH / 2 - b.center.dy * scale + 8;
    return Matrix4.identity()
      ..translateByDouble(dx, dy, 0, 1)
      ..scaleByDouble(scale, scale, 1, 1);
  }

  void _refit() {
    final m = _fitMatrix(_layout);
    if (m == null) return;
    _matFrom = _tc.value.clone();
    _matTo = m;
    _from = Map.of(_shown);
    _to = Map.of(_layout.positions);
    _anim.forward(from: 0);
  }

  void _zoomBy(double f) {
    final m = _tc.value.clone();
    final centre = Offset(_viewport.width / 2, _viewport.height * 0.3);
    final scene = _tc.toScene(centre);
    m.translateByDouble(scene.dx, scene.dy, 0, 1);
    m.scaleByDouble(f, f, 1, 1);
    m.translateByDouble(-scene.dx, -scene.dy, 0, 1);
    _tc.value = m;
  }

  // ── Navigation ─────────────────────────────────────────────────────────────

  void _pushTrail(_TrailEntry e) {
    _trail.removeWhere((t) => t.mode == e.mode && t.id == e.id);
    _trail.add(e);
    if (_trail.length > 12) _trail.removeAt(0);
    // Keep the newest crumb in view.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_trailScroll.hasClients) {
        _trailScroll.animateTo(_trailScroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      }
    });
  }

  void _showOverview({bool animate = true}) {
    if (_overviewLayout == null) return;
    _mode = _Mode.overview;
    _passages = null;
    _searchResult = null;
    _selectedId = null;
    _highlight = {};
    _panelError = null;
    _setLayout(_applyOverviewEmphasis(_overviewLayout!), animate: animate);
    _snapPanel(0.36);
  }

  Future<void> _focusTopic(String id, {String? bookId, bool record = true}) async {
    final m = _map;
    if (m == null) return;
    final node = m.topic(id);
    if (node == null) return;
    final seq = ++_requestSeq;
    setState(() {
      _mode = _Mode.topic;
      _passages = null;
      _panelBook = bookId;
      _panelLoading = true;
      _panelError = null;
      _selectedId = id;
      _highlight = {};
      _searchFocus.unfocus();
      _suggestions = const [];
    });
    if (record) _pushTrail(_TrailEntry(_Mode.topic, id, node.label, node.color, bookId: bookId));
    try {
      final d = await _api.topic(id);
      if (!mounted || seq != _requestSeq) return;
      _topic = d;
      _panelLoading = false;
      _setLayout(_buildTopicLayout(d), emergeFrom: id);
      if (bookId != null) {
        _highlight = {'book:$bookId'};
        _openPassages(id, bookId: bookId);
      } else {
        _snapPanel(0.40);
      }
    } on GraphBuilding catch (b) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _building = b;
        _panelLoading = false;
      });
      _pollTimer = Timer(const Duration(milliseconds: 2500), _loadMap);
    } catch (e) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _panelLoading = false;
        _panelError = 'Could not load this topic. $e';
      });
    }
  }

  Future<void> _focusBook(String id, {bool record = true}) async {
    final m = _map;
    if (m == null) return;
    final seq = ++_requestSeq;
    setState(() {
      _mode = _Mode.book;
      _passages = null;
      _panelLoading = true;
      _panelError = null;
      _selectedId = 'book:$id';
      _highlight = {};
      _searchFocus.unfocus();
      _suggestions = const [];
    });
    try {
      final d = await _api.book(id);
      if (!mounted || seq != _requestSeq) return;
      _book = d;
      _panelLoading = false;
      if (record) _pushTrail(_TrailEntry(_Mode.book, id, d.book.title, AppColors.gold));
      _setLayout(_buildBookLayout(d), emergeFrom: 'book:$id');
      _snapPanel(0.40);
    } on GraphBuilding catch (b) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _building = b;
        _panelLoading = false;
      });
      _pollTimer = Timer(const Duration(milliseconds: 2500), _loadMap);
    } catch (e) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _panelLoading = false;
        _panelError = 'Could not load this book. $e';
      });
    }
  }

  Future<void> _openPassages(String topicId, {String? bookId, int? section, String? sectionTitle, String sort = 'score'}) async {
    final seq = ++_requestSeq;
    setState(() {
      _panelLoading = true;
      _panelError = null;
      if (bookId != null) _highlight = {'book:$bookId'};
    });
    try {
      final page = await _api.passages(topicId, book: bookId, section: section, sort: section != null && sort == 'score' ? 'position' : sort);
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _panelLoading = false;
        _passages = _PassagesView(page: page, loaded: page.passages, section: section, sectionTitle: sectionTitle);
      });
      _snapPanel(0.55);
    } catch (e) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _panelLoading = false;
        _panelError = 'Could not load passages. $e';
      });
    }
  }

  Future<void> _loadMorePassages() async {
    final v = _passages;
    if (v == null || v.loadingMore) return;
    setState(() => _passages = v.copyWith(loadingMore: true));
    try {
      final page = await _api.passages(
        v.page.topic.id,
        book: v.page.book?.id,
        section: v.section,
        sort: v.page.sort,
        offset: v.loaded.length,
      );
      if (!mounted || _passages != v && _passages?.page.topic.id != v.page.topic.id) return;
      setState(() => _passages = v.copyWith(page: page, loaded: [...v.loaded, ...page.passages], loadingMore: false));
    } catch (_) {
      if (mounted) setState(() => _passages = v.copyWith(loadingMore: false));
    }
  }

  Future<void> _runSearch(String q) async {
    final query = q.trim();
    if (query.isEmpty || _map == null) return;
    final seq = ++_requestSeq;
    _searchFocus.unfocus();
    setState(() {
      _mode = _Mode.search;
      _passages = null;
      _panelLoading = true;
      _panelError = null;
      _selectedId = null;
      _suggestions = const [];
    });
    try {
      final r = await _api.search(query);
      if (!mounted || seq != _requestSeq) return;
      _searchResult = r;
      _panelLoading = false;
      _pushTrail(_TrailEntry(_Mode.search, query, '“$query”', AppColors.accent));
      // Show the overview with the matching topics lit up.
      _highlight = _searchTopicIds();
      _setLayout(_applyOverviewEmphasis(_overviewLayout!));
      _snapPanel(0.55);
    } catch (e) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _panelLoading = false;
        _panelError = 'Search failed. $e';
      });
    }
  }

  void _goTo(_TrailEntry e) {
    final idx = _trail.indexOf(e);
    if (idx >= 0) _trail.removeRange(idx, _trail.length);
    switch (e.mode) {
      case _Mode.topic:
        _focusTopic(e.id, bookId: e.bookId);
      case _Mode.book:
        _focusBook(e.id);
      case _Mode.search:
        _search.text = e.id;
        _runSearch(e.id);
      case _Mode.overview:
        _showOverview();
    }
  }

  bool _goBack() {
    if (_passages != null && _mode != _Mode.search) {
      setState(() => _passages = null);
      _snapPanel(0.40);
      return true;
    }
    if (_trail.length >= 2) {
      _trail.removeLast();
      _goTo(_trail.last);
      return true;
    }
    if (_mode != _Mode.overview) {
      _trail.clear();
      _showOverview();
      return true;
    }
    return false;
  }

  void _snapPanel(double size) {
    if (!_panel.isAttached) return;
    _panel.animateTo(size, duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic);
  }

  void _filterGroup(String? g) {
    setState(() => _groupFilter = g);
    if (_mode == _Mode.overview && _overviewLayout != null) {
      _layout = _applyOverviewEmphasis(_overviewLayout!);
    }
  }

  Future<void> _openPassage(Passage p, {String? fromTopic}) async {
    await showAppSheet(
      context,
      PassageReaderSheet(
        api: _api,
        passage: p,
        fromTopicId: fromTopic,
        onTopic: (t) => _focusTopic(t.id, bookId: p.bookId),
        onAsk: widget.onSelectPrompt == null
            ? null
            : (prompt) {
                Navigator.of(context).pop(); // close the graph, hand the prompt to chat
                widget.onSelectPrompt!(prompt);
              },
      ),
      initialSize: 0.85,
    );
  }

  void _askAboutTopic(String prompt) {
    if (widget.onSelectPrompt == null) return;
    Navigator.of(context).pop();
    widget.onSelectPrompt!(prompt);
  }

  // ── Canvas interaction ─────────────────────────────────────────────────────

  // A DoubleTapGestureRecognizer on the canvas would hold every single tap in
  // the gesture arena (and, nested inside InteractiveViewer's scale
  // recognizer, taps were never delivered at all), so double-tap is detected
  // by hand from consecutive taps on the same node.
  String? _lastTapId;
  DateTime _lastTapAt = DateTime.fromMillisecondsSinceEpoch(0);

  void _onCanvasTap(Offset scenePoint) {
    final id = hitTestNode(_layout, _shown, scenePoint);
    if (id == null) {
      if (_hoveredId != null) setState(() => _hoveredId = null);
      return;
    }
    final now = DateTime.now();
    final isDouble = id == _lastTapId && now.difference(_lastTapAt) < const Duration(milliseconds: 400);
    _lastTapId = id;
    _lastTapAt = now;
    if (id.startsWith('book:')) {
      final bookId = id.substring(5);
      if (isDouble) {
        _focusBook(bookId);
        return;
      }
      if (_mode == _Mode.topic && _topic != null) {
        setState(() {
          _selectedId = id;
          _highlight = {id};
        });
        _openPassages(_topic!.topic.id, bookId: bookId);
      } else {
        _focusBook(bookId);
      }
      return;
    }
    if (_mode == _Mode.book && _book != null) {
      _focusTopic(id, bookId: _book!.book.id);
    } else if (_mode == _Mode.topic && _topic?.topic.id == id) {
      // Tapping the focus again re-centres.
      _refit();
    } else {
      _focusTopic(id);
    }
  }

  void _onHover(Offset local) {
    final id = hitTestNode(_layout, _shown, _tc.toScene(local));
    if (id != _hoveredId) setState(() => _hoveredId = id);
  }

  void _onSearchChanged(String text) {
    final q = text.trim().toLowerCase();
    final m = _map;
    if (q.length < 2 || m == null) {
      if (_suggestions.isNotEmpty) setState(() => _suggestions = const []);
      return;
    }
    final hits = m.topics.where((t) => t.label.toLowerCase().contains(q) || t.blurb.toLowerCase().contains(q)).take(6).toList();
    setState(() => _suggestions = hits);
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final ready = _map != null && _building == null && _mapError == null;

    return PopScope(
      canPop: !ready || (_trail.length < 2 && _mode == _Mode.overview && _passages == null),
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _goBack();
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Row(
            children: [
              Icon(Icons.hub, color: AppColors.accent, size: 22),
              SizedBox(width: AppSpacing.sm),
              Text('Knowledge Graph'),
            ],
          ),
          actions: [
            IconButton(
              tooltip: 'Whole library',
              icon: const Icon(Icons.public),
              onPressed: ready ? () { _trail.clear(); _showOverview(); } : null,
            ),
            IconButton(
              tooltip: 'How to use the graph',
              icon: const Icon(Icons.help_outline),
              onPressed: () => _showHelp(context),
            ),
          ],
        ),
        body: !ready
            ? (_building != null || _mapError != null
                ? BuildingView(
                    status: _building?.status ?? '',
                    progress: _building?.progress ?? 0,
                    error: _mapError,
                    onRetry: _loadMap,
                  )
                : const Center(child: CircularProgressIndicator()))
            : Column(
                children: [
                  _buildSearchBar(theme),
                  if (_trail.isNotEmpty) _buildTrail(theme),
                  Expanded(
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final size = Size(constraints.maxWidth, constraints.maxHeight);
                        if (size != _viewport) {
                          final first = _viewport == Size.zero;
                          _viewport = size;
                          WidgetsBinding.instance.addPostFrameCallback((_) {
                            if (!mounted) return;
                            if (first) {
                              _setLayout(_layout, animate: false);
                            } else {
                              _refit();
                            }
                          });
                        }
                        return Stack(
                          children: [
                            Positioned.fill(child: _buildCanvas(isDark)),
                            // On phones the legend would cover the map; the
                            // panel's theme chips do the same job there.
                            if (_mode == _Mode.overview && size.width >= 560)
                              Positioned(left: 12, top: 10, child: _buildLegend(theme)),
                            Positioned(
                              right: 12,
                              top: 10,
                              child: Column(
                                children: [
                                  _roundButton(Icons.add, () => _zoomBy(1.3), 'Zoom in'),
                                  const SizedBox(height: 6),
                                  _roundButton(Icons.remove, () => _zoomBy(0.77), 'Zoom out'),
                                  const SizedBox(height: 6),
                                  _roundButton(Icons.center_focus_strong, _refit, 'Fit'),
                                ],
                              ),
                            ),
                            if (_hoveredId != null && !_layout.nodes[_hoveredId]!.isFocus)
                              Positioned(
                                left: 12,
                                bottom: size.height * 0.15 + 8,
                                child: _hoverHint(theme),
                              ),
                            DraggableScrollableSheet(
                              controller: _panel,
                              initialChildSize: 0.36,
                              minChildSize: 0.14,
                              maxChildSize: 0.92,
                              snap: true,
                              snapSizes: const [0.14, 0.36, 0.55, 0.92],
                              builder: (context, scroll) => _buildPanel(theme, scroll),
                            ),
                          ],
                        );
                      },
                    ),
                  ),
                ],
              ),
      ),
    );
  }

  Widget _buildSearchBar(ThemeData theme) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: _search,
            focusNode: _searchFocus,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: 'Search a topic, a feeling, or a phrase…',
              prefixIcon: IconButton(
                tooltip: 'Search',
                icon: const Icon(Icons.search),
                onPressed: () => _runSearch(_search.text),
              ),
              isDense: true,
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _search.clear();
                        setState(() => _suggestions = const []);
                      },
                    ),
            ),
            onChanged: (v) {
              _onSearchChanged(v);
              setState(() {});
            },
            onSubmitted: _runSearch,
          ),
          if (_suggestions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: SizedBox(
                height: 34,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: [
                    for (final t in _suggestions)
                      Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: TopicChip(
                          label: t.label,
                          color: t.color,
                          onTap: () {
                            _search.text = t.label;
                            _focusTopic(t.id);
                          },
                        ),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildTrail(ThemeData theme) {
    return SizedBox(
      height: 38,
      child: ListView(
        controller: _trailScroll,
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 4),
        children: [
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: TopicChip(
              label: 'Library',
              color: theme.colorScheme.onSurfaceVariant,
              onTap: () {
                _trail.clear();
                _showOverview();
              },
            ),
          ),
          for (var i = 0; i < _trail.length; i++) ...[
            Icon(Icons.chevron_right, size: 16, color: theme.colorScheme.onSurfaceVariant),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2),
              child: TopicChip(
                label: _trail[i].label,
                color: _trail[i].color,
                selected: i == _trail.length - 1,
                onTap: () => _goTo(_trail[i]),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildCanvas(bool isDark) {
    // The tap detector sits *outside* InteractiveViewer and converts viewport
    // points to scene coordinates (like hover does). Inside the viewer the
    // hit-test depends on the fixed-size canvas child and taps on nodes near
    // its edge were silently lost.
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapUp: (d) => _onCanvasTap(_tc.toScene(d.localPosition)),
      child: MouseRegion(
        onHover: (e) => _onHover(e.localPosition),
        onExit: (_) {
          if (_hoveredId != null) setState(() => _hoveredId = null);
        },
        cursor: _hoveredId != null ? SystemMouseCursors.click : SystemMouseCursors.grab,
        child: InteractiveViewer(
          transformationController: _tc,
          boundaryMargin: const EdgeInsets.all(4000),
          minScale: 0.1,
          maxScale: 3.5,
          clipBehavior: Clip.none,
          child: SizedBox(
            width: _kCanvas,
            height: _kCanvas,
            child: CustomPaint(
              painter: GraphPainter(
                layout: _layout,
                positions: _shown,
                selectedId: _selectedId,
                hoveredId: _hoveredId,
                highlightIds: _highlight,
                isDark: isDark,
                scale: _zoom,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLegend(ThemeData theme) {
    final m = _map!;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface.withValues(alpha: 0.86),
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          for (final g in m.groups)
            InkWell(
              onTap: () => _filterGroup(_groupFilter == g.id ? null : g.id),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 1.5),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    GroupDot(groupColor(g.id), size: 9),
                    const SizedBox(width: 6),
                    Text(
                      g.label,
                      style: theme.textTheme.labelSmall?.copyWith(
                        fontWeight: _groupFilter == g.id ? FontWeight.w800 : FontWeight.w500,
                        color: _groupFilter != null && _groupFilter != g.id
                            ? theme.colorScheme.onSurfaceVariant
                            : theme.colorScheme.onSurface,
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _hoverHint(ThemeData theme) {
    final node = _layout.nodes[_hoveredId];
    if (node == null) return const SizedBox.shrink();
    String detail = '';
    if (node.kind == 'topic') {
      final t = _map?.topic(node.id);
      if (t != null) detail = '${t.blurb} · ${t.mentions} passages';
    } else {
      detail = _mode == _Mode.topic ? 'Tap for passages · double-tap for the book' : 'Tap to open the book';
    }
    return Container(
      constraints: const BoxConstraints(maxWidth: 260),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(node.label, style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700)),
          if (detail.isNotEmpty) Text(detail, style: theme.textTheme.labelSmall),
        ],
      ),
    );
  }

  Widget _roundButton(IconData icon, VoidCallback onTap, String tooltip) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surface.withValues(alpha: 0.9),
      shape: CircleBorder(side: BorderSide(color: theme.colorScheme.outlineVariant)),
      child: IconButton(
        tooltip: tooltip,
        icon: Icon(icon, size: 20),
        onPressed: onTap,
        constraints: const BoxConstraints(minWidth: 38, minHeight: 38),
        padding: EdgeInsets.zero,
      ),
    );
  }

  Widget _buildPanel(ThemeData theme, ScrollController scroll) {
    final actions = GraphActions(
      focusTopic: (id, {bookId}) => _focusTopic(id, bookId: bookId),
      focusBook: (id) => _focusBook(id),
      openPassages: (id, {bookId, section, sectionTitle}) =>
          _openPassages(id, bookId: bookId, section: section, sectionTitle: sectionTitle),
      openPassage: (p, {fromTopic}) => _openPassage(p, fromTopic: fromTopic),
      showOverview: () {
        _trail.clear();
        _showOverview();
      },
      filterGroup: _filterGroup,
      ask: widget.onSelectPrompt == null ? null : _askAboutTopic,
    );

    Widget body;
    if (_panelLoading) {
      body = ListView(
        controller: scroll,
        children: const [
          SizedBox(height: 60),
          Center(child: CircularProgressIndicator()),
        ],
      );
    } else if (_panelError != null) {
      body = ListView(
        controller: scroll,
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Text(_panelError!, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.sm),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(onPressed: actions.showOverview, child: const Text('Back to the map')),
          ),
        ],
      );
    } else if (_passages != null) {
      final v = _passages!;
      body = PassagesPanel(
        page: v.page,
        loaded: v.loaded,
        sectionTitle: v.sectionTitle,
        loadingMore: v.loadingMore,
        actions: actions,
        controller: scroll,
        onBack: () {
          setState(() => _passages = null);
          if (_mode == _Mode.search && _searchResult == null) _showOverview();
        },
        onLoadMore: _loadMorePassages,
        onSort: (s) => _openPassages(v.page.topic.id, bookId: v.page.book?.id, section: v.section,
            sectionTitle: v.sectionTitle, sort: s),
      );
    } else {
      switch (_mode) {
        case _Mode.topic:
          body = _topic == null
              ? const SizedBox.shrink()
              : TopicPanel(detail: _topic!, actions: actions, controller: scroll, highlightBookId: _panelBook);
        case _Mode.book:
          body = _book == null ? const SizedBox.shrink() : BookPanel(detail: _book!, actions: actions, controller: scroll);
        case _Mode.search:
          body = _searchResult == null
              ? const SizedBox.shrink()
              : SearchPanel(result: _searchResult!, actions: actions, controller: scroll);
        case _Mode.overview:
          body = OverviewPanel(map: _map!, groupFilter: _groupFilter, actions: actions, controller: scroll);
      }
    }

    return Container(
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(AppSpacing.radiusLg)),
        border: Border.all(color: theme.colorScheme.outlineVariant),
        boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 14, offset: Offset(0, -2))],
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 8, bottom: 6),
            child: Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.5),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          Expanded(child: body),
        ],
      ),
    );
  }

  void _showHelp(BuildContext context) {
    final theme = Theme.of(context);
    showAppSheet(
      context,
      ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Text('Reading the library as a map', style: theme.textTheme.titleLarge),
          const SizedBox(height: AppSpacing.md),
          _help(theme, Icons.circle, 'Topics', 'Every disc is a recovery topic, coloured by theme. Bigger discs are discussed more. Lines join topics that appear together in the same passages.'),
          _help(theme, Icons.touch_app_outlined, 'Focus', 'Tap a topic to centre it: the ring around it holds the topics it leads to, and the outer ring holds the books that discuss it most.'),
          _help(theme, Icons.menu_book_outlined, 'Books', 'Tap a book for its passages on the topic; double-tap (or tap its title) to see everything the book talks about, chapter by chapter.'),
          _help(theme, Icons.alt_route, 'Hop', 'Each passage lists the other topics it touches. Tap one to jump there — that is how you travel through the literature.'),
          _help(theme, Icons.search, 'Search', 'Type a feeling, a Step, or a phrase. Matching topics light up on the map and the best passages are listed.'),
          _help(theme, Icons.auto_awesome, 'Ask', 'From any topic or passage, hand it to the chat to talk it through.'),
        ],
      ),
      initialSize: 0.7,
    );
  }

  Widget _help(ThemeData theme, IconData icon, String title, String body) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: AppColors.accent, size: 20),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  Text(body, style: theme.textTheme.bodySmall),
                ],
              ),
            ),
          ],
        ),
      );
}
