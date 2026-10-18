/// Concept graph — the whole library as a map of thousands of ideas.
///
/// * **Map**: every concept at its place on a precomputed map; the ones that
///   bridge the most other ideas are biggest. Pan and zoom to fill in the
///   cloud.
/// * **Select** any concept (tap it, or search): lines run to its strongest
///   peers and the panel lists *all* of them, plus the books, chapters and
///   passages where it occurs.
/// * **Pivot** anywhere: a peer opens the passages where the two ideas meet;
///   a book or chapter lists the concepts inside it; every concept, book,
///   chapter and passage leads on to more. The trail keeps your path.
/// * **Research this** hands a question to chat in research mode.
///
/// Data: `/api/graph2/*` (src/rag/concept_graph.py).
library;

import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/features/graph/graph_api.dart';
import 'package:sobriety_copilot_mobile/features/graph/graph_models.dart' as g1;
import 'package:sobriety_copilot_mobile/features/graph/graph_panels.dart' show BuildingView, GroupDot;
import 'package:sobriety_copilot_mobile/features/graph/passage_reader.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

import 'concept_api.dart';
import 'concept_models.dart';
import 'concept_painter.dart';

enum _View { overview, node, meet, book, chapter, search }

class _Crumb {
  final _View view;
  final String label;
  final String? nodeId;
  final String? otherId;
  final String? docId;
  final int? section;
  const _Crumb(this.view, this.label, {this.nodeId, this.otherId, this.docId, this.section});
}

class ConceptGraphScreen extends ConsumerStatefulWidget {
  /// Hands a research question to chat (closes the graph first).
  final void Function(String prompt)? onResearch;

  /// Called when the server has no concept graph, to show the older topic graph instead.
  final VoidCallback? onUnsupported;

  const ConceptGraphScreen({super.key, this.onResearch, this.onUnsupported});

  @override
  ConsumerState<ConceptGraphScreen> createState() => _ConceptGraphScreenState();
}

class _ConceptGraphScreenState extends ConsumerState<ConceptGraphScreen> with SingleTickerProviderStateMixin {
  late final ConceptApi _api;
  late final GraphApi _readerApi;
  final TransformationController _tc = TransformationController();
  final DraggableScrollableController _panel = DraggableScrollableController();
  final TextEditingController _search = TextEditingController();
  final FocusNode _searchFocus = FocusNode();
  final LabelCache _labels = LabelCache();
  late final AnimationController _cam = AnimationController(vsync: this, duration: const Duration(milliseconds: 280))
    ..addListener(_onCamTick);
  Matrix4? _camFrom, _camTo;
  final FocusNode _canvasFocus = FocusNode(debugLabel: 'concept canvas');

  /// True while the camera still shows the fitted map (so a resize re-fits it).
  bool _fitted = true;

  ConceptMap? _map;
  ConceptGraphBuilding? _building;
  String? _error;
  Timer? _poll;
  Timer? _debounce;
  Size _viewport = Size.zero;

  _View _view = _View.overview;
  int? _selected;
  int? _hovered;
  Map<int, double> _peerStrength = const {};
  Set<int> _emphasis = const {};
  String? _groupFilter;
  final List<_Crumb> _trail = [];

  NodeDetail? _detail;
  MeetResult? _meet;
  BookConcepts? _book;
  ChapterConcepts? _chapter;
  ConceptSearch? _serverSearch;
  List<ConceptNode> _suggestions = const [];
  bool _loading = false;
  String? _panelError;
  int _seq = 0;
  int _tab = 0; // node view: 0 connected, 1 books, 2 chapters, 3 passages
  int _peerShown = 60;

  @override
  void initState() {
    super.initState();
    final base = ref.read(appConfigProvider).baseUrl;
    _api = ConceptApi(base);
    _readerApi = GraphApi(base);
    _tc.addListener(_keepInView);
    _loadMap();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _debounce?.cancel();
    _cam.dispose();
    _tc.dispose();
    _panel.dispose();
    _search.dispose();
    _searchFocus.dispose();
    _canvasFocus.dispose();
    super.dispose();
  }

  // ── data ─────────────────────────────────────────────────────────────────

  Future<void> _loadMap() async {
    _poll?.cancel();
    try {
      final m = await _api.map();
      if (!mounted) return;
      setState(() {
        _map = m;
        _building = null;
        _error = null;
      });
      WidgetsBinding.instance.addPostFrameCallback((_) => _fit(animate: false));
    } on ConceptGraphBuilding catch (b) {
      if (!mounted) return;
      setState(() => _building = b);
      _poll = Timer(const Duration(seconds: 2), _loadMap);
    } on ConceptGraphUnsupported {
      if (!mounted) return;
      widget.onUnsupported?.call();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Could not reach the server. $e');
    }
  }

  Future<T?> _fetch<T>(Future<T> Function() f) async {
    final seq = ++_seq;
    setState(() {
      _loading = true;
      _panelError = null;
    });
    try {
      final out = await f();
      if (!mounted || seq != _seq) return null;
      setState(() => _loading = false);
      return out;
    } catch (e) {
      if (!mounted || seq != _seq) return null;
      setState(() {
        _loading = false;
        _panelError = 'Could not load this. $e';
      });
      return null;
    }
  }

  // ── navigation ───────────────────────────────────────────────────────────

  void _push(_Crumb c) {
    if (_trail.isNotEmpty) {
      final last = _trail.last;
      if (last.view == c.view && last.nodeId == c.nodeId && last.otherId == c.otherId && last.docId == c.docId && last.section == c.section) {
        return;
      }
    }
    _trail.add(c);
    if (_trail.length > 30) _trail.removeAt(0);
  }

  Future<void> _selectNode(String id, {bool record = true, bool center = true}) async {
    final m = _map;
    if (m == null) return;
    final idx = m.index[id];
    if (idx == null) return;
    _searchFocus.unfocus();
    setState(() {
      _view = _View.node;
      _selected = idx;
      _tab = 0;
      _peerShown = 60;
      _detail = null;
      _peerStrength = {for (final p in m.nodes[idx].topPeers) p: 0.6};
      _emphasis = const {};
      _suggestions = const [];
    });
    if (record) _push(_Crumb(_View.node, m.nodes[idx].label, nodeId: id));
    if (center) _centerOn(idx);
    _openPanel(0.45);
    final d = await _fetch(() => _api.node(id));
    if (d == null) return;
    final maxW = d.peers.fold<double>(0.01, (a, p) => max(a, p.weight));
    setState(() {
      _detail = d;
      _peerStrength = {
        for (final p in d.peers.take(220))
          if (m.index[p.id] != null) m.index[p.id]!: (p.weight / maxW).clamp(0.05, 1.0),
      };
    });
  }

  Future<void> _openMeet(String a, String b, {bool record = true}) async {
    final m = _map!;
    final ia = m.index[a], ib = m.index[b];
    setState(() {
      _view = _View.meet;
      _meet = null;
      if (ia != null) _selected = ia;
      _peerStrength = {if (ib != null) ib: 1.0};
    });
    if (record && ia != null && ib != null) {
      _push(_Crumb(_View.meet, '${m.nodes[ia].label} + ${m.nodes[ib].label}', nodeId: a, otherId: b));
    }
    _openPanel(0.6);
    final r = await _fetch(() => _api.meet(a, b, limit: 15));
    if (r != null) setState(() => _meet = r);
  }

  Future<void> _moreMeet() async {
    final cur = _meet;
    if (cur == null) return;
    final r = await _fetch(() => _api.meet(cur.a.id, cur.b.id, offset: cur.passages.length, limit: 15));
    if (r != null) {
      setState(() => _meet = MeetResult(a: cur.a, b: cur.b, total: cur.total, passages: [...cur.passages, ...r.passages]));
    }
  }

  Future<void> _openBook(String docId, String title, {bool record = true}) async {
    setState(() {
      _view = _View.book;
      _book = null;
    });
    if (record) _push(_Crumb(_View.book, title, docId: docId));
    _openPanel(0.6);
    final b = await _fetch(() => _api.book(docId));
    if (b == null) return;
    final m = _map!;
    setState(() {
      _book = b;
      _selected = null;
      _peerStrength = const {};
      _emphasis = {for (final c in b.concepts.take(200)) if (m.index[c.id] != null) m.index[c.id]!};
    });
  }

  Future<void> _openChapter(String docId, int section, String title, {bool record = true}) async {
    setState(() {
      _view = _View.chapter;
      _chapter = null;
    });
    if (record) _push(_Crumb(_View.chapter, title, docId: docId, section: section));
    _openPanel(0.6);
    final c = await _fetch(() => _api.chapter(docId, section));
    if (c == null) return;
    final m = _map!;
    setState(() {
      _chapter = c;
      _selected = null;
      _peerStrength = const {};
      _emphasis = {for (final n in c.concepts.take(150)) if (m.index[n.id] != null) m.index[n.id]!};
    });
  }

  void _showOverview() {
    setState(() {
      _view = _View.overview;
      _selected = null;
      _peerStrength = const {};
      _emphasis = _groupFilter == null ? const {} : _groupSet(_groupFilter!);
      _trail.clear();
    });
    _fit(panel: max(_panelSize, 0.22));
    _openPanel(0.22);
  }

  void _goTo(int i) {
    final c = _trail[i];
    _trail.removeRange(i + 1, _trail.length);
    switch (c.view) {
      case _View.node:
        _selectNode(c.nodeId!, record: false);
      case _View.meet:
        _openMeet(c.nodeId!, c.otherId!, record: false);
      case _View.book:
        _openBook(c.docId!, c.label, record: false);
      case _View.chapter:
        _openChapter(c.docId!, c.section!, c.label, record: false);
      default:
        _showOverview();
    }
  }

  bool _goBack() {
    if (_trail.length >= 2) {
      _goTo(_trail.length - 2);
      return true;
    }
    if (_view != _View.overview) {
      _showOverview();
      return true;
    }
    return false;
  }

  Set<int> _groupSet(String group) => {for (final n in _map!.nodes) if (n.group == group) n.index};

  void _filterGroup(String? g) {
    setState(() {
      _groupFilter = g;
      if (_view == _View.overview) _emphasis = g == null ? const {} : _groupSet(g);
    });
  }

  // ── search ───────────────────────────────────────────────────────────────

  void _onSearchChanged(String v) {
    final m = _map;
    if (m == null) return;
    final q = v.trim().toLowerCase();
    if (q.isEmpty) {
      setState(() {
        _suggestions = const [];
        if (_view == _View.overview) _emphasis = const {};
      });
      return;
    }
    final starts = <ConceptNode>[], contains = <ConceptNode>[];
    for (final n in m.nodes) {
      final l = n.label.toLowerCase();
      if (l.startsWith(q)) {
        starts.add(n);
      } else if (l.contains(q)) {
        contains.add(n);
      }
    }
    int byProm(ConceptNode a, ConceptNode b) => b.prominence.compareTo(a.prominence);
    starts.sort(byProm);
    contains.sort(byProm);
    final hits = [...starts, ...contains];
    setState(() {
      _suggestions = hits.take(10).toList();
      if (_view == _View.overview) _emphasis = {for (final n in hits.take(300)) n.index};
    });
  }

  Future<void> _runSearch(String q) async {
    if (q.trim().isEmpty) return;
    _searchFocus.unfocus();
    final exact = _map?.nodes.where((n) => n.label.toLowerCase() == q.trim().toLowerCase()).toList() ?? const [];
    if (exact.isNotEmpty) {
      exact.sort((a, b) => b.prominence.compareTo(a.prominence));
      _selectNode(exact.first.id);
      return;
    }
    setState(() {
      _view = _View.search;
      _serverSearch = null;
    });
    _openPanel(0.55);
    final r = await _fetch(() => _api.search(q.trim()));
    if (r != null) setState(() => _serverSearch = r);
  }

  // ── canvas ───────────────────────────────────────────────────────────────

  double get _zoom => _tc.value.getMaxScaleOnAxis();

  /// Where the camera is headed: the end of a running move, else where it is.
  Matrix4 get _camTarget => _cam.isAnimating && _camTo != null ? _camTo! : _tc.value;

  double get _panelSize => _panel.isAttached ? _panel.size : 0.22;

  /// Canvas height left above a bottom panel of [panel] (fraction of the
  /// canvas; capped so a tall panel doesn't squeeze the map into a sliver).
  double _visibleHeight([double? panel]) => _viewport.height * (1 - (panel ?? _panelSize).clamp(0.1, 0.6));

  /// Scale at which the whole map fits above the panel.
  double _fitScaleFor(double visibleH) => min(_viewport.width, visibleH) / kSceneSize;
  double get _fitScale => _fitScaleFor(_visibleHeight(0.22));

  /// Zoom limits: out to half the fitted map, in to 8×.
  double get _minScale => max(0.02, _fitScale * 0.5);
  static const double _maxScale = 8;

  // The InteractiveViewer is unbounded (a finite boundaryMargin pins the map
  // to the left edge whenever map + margin is narrower than the viewport, e.g.
  // on a wide desktop window); this keeps part of the map on screen instead.
  Matrix4 _clamp(Matrix4 m) {
    if (_viewport == Size.zero) return m;
    final side = kSceneSize * m.getMaxScaleOnAxis();
    final t = m.getTranslation();
    double axis(double v, double view) {
      final keep = min(side, view) * 0.35;
      return v.clamp(keep - side, view - keep).toDouble();
    }

    final x = axis(t.x, _viewport.width), y = axis(t.y, _viewport.height);
    if (x == t.x && y == t.y) return m;
    return m.clone()..setTranslationRaw(x, y, t.z);
  }

  void _keepInView() {
    final c = _clamp(_tc.value);
    if (!identical(c, _tc.value)) _tc.value = c;
  }

  /// Moves the camera to [target], animated unless [animate] is false.
  void _moveTo(Matrix4 target, {bool animate = true}) {
    target = _clamp(target);
    if (!animate) {
      _cam.stop();
      _tc.value = target;
      return;
    }
    _camFrom = _tc.value.clone();
    _camTo = target;
    _cam.forward(from: 0);
  }

  void _onCamTick() {
    final from = _camFrom, to = _camTo;
    if (from == null || to == null) return;
    _tc.value = Matrix4Tween(begin: from, end: to).lerp(Curves.easeOutCubic.transform(_cam.value));
  }

  /// Fits the whole map into the canvas above the panel ([panel] = the
  /// panel size to allow for, default its current size).
  void _fit({bool animate = true, double? panel}) {
    if (_viewport == Size.zero) return;
    final h = _visibleHeight(panel);
    final s = _fitScaleFor(h);
    final dx = (_viewport.width - kSceneSize * s) / 2;
    final dy = (h - kSceneSize * s) / 2;
    _moveTo(
      Matrix4.identity()
        ..translateByDouble(dx, dy, 0, 1)
        ..scaleByDouble(s, s, 1, 1),
      animate: animate,
    );
    _fitted = true;
  }

  void _centerOn(int idx) {
    if (_viewport == Size.zero) return;
    final p = scenePos(_map!.nodes[idx]);
    final z = max(_camTarget.getMaxScaleOnAxis(), min(_viewport.width, _viewport.height) / kSceneSize * 2.2);
    // Selecting opens the panel to at least 0.45; centre in what stays visible.
    final target = Offset(_viewport.width / 2, _visibleHeight(max(_panelSize, 0.45)) / 2);
    _fitted = false;
    _moveTo(Matrix4.identity()
      ..translateByDouble(target.dx - p.dx * z, target.dy - p.dy * z, 0, 1)
      ..scaleByDouble(z, z, 1, 1));
  }

  /// Pans the view by [d] screen pixels (keyboard arrows).
  void _panBy(Offset d) {
    _fitted = false;
    _moveTo(Matrix4.translationValues(d.dx, d.dy, 0) * _camTarget);
  }

  /// Keeps the map where it was on screen when the canvas changes size,
  /// re-fitting it instead if it was still showing the fitted map.
  void _onResize(Size old) {
    if (old == Size.zero || _fitted) {
      _fit(animate: false);
      return;
    }
    final d = Offset(_viewport.width - old.width, _viewport.height - old.height) / 2;
    _moveTo(Matrix4.translationValues(d.dx, d.dy, 0) * _camTarget, animate: false);
  }

  void _zoomBy(double f) {
    // Zoom about the middle of the visible map (above the panel). Repeated
    // clicks build on the move in flight rather than the frame on screen.
    _fitted = false;
    final from = _camTarget;
    final c = Offset(_viewport.width / 2, _visibleHeight() / 2);
    final scene = MatrixUtils.transformPoint(Matrix4.inverted(from), c);
    final z = (from.getMaxScaleOnAxis() * f).clamp(_minScale, _maxScale);
    _moveTo(Matrix4.identity()
      ..translateByDouble(c.dx - scene.dx * z, c.dy - scene.dy * z, 0, 1)
      ..scaleByDouble(z, z, 1, 1));
  }

  void _openPanel(double size) {
    if (!_panel.isAttached) return;
    if (_panel.size < size - 0.02) {
      _panel.animateTo(size, duration: const Duration(milliseconds: 220), curve: Curves.easeOut);
    }
  }

  void _onTap(Offset local) {
    final m = _map;
    if (m == null) return;
    final idx = hitTestConcept(m, _tc.toScene(local), _zoom, _labels, prefer: _peerStrength);
    if (idx == null) return;
    final n = m.nodes[idx];
    if (_view == _View.node && _selected != null && idx != _selected && _peerStrength.containsKey(idx)) {
      // Tapping a lit peer opens where the two meet; the panel offers "go to".
      _openMeet(m.nodes[_selected!].id, n.id);
    } else {
      _selectNode(n.id, center: false);
    }
  }

  void _onHover(Offset local) {
    final m = _map;
    if (m == null) return;
    final idx = hitTestConcept(m, _tc.toScene(local), _zoom, _labels, prefer: _peerStrength);
    if (idx != _hovered) setState(() => _hovered = idx);
  }

  // ── passages / research ──────────────────────────────────────────────────

  Future<void> _openPassage(CPassage p) async {
    final passage = g1.Passage(
      chunkId: '',
      bookId: p.docId,
      bookTitle: p.bookTitle,
      docId: p.docId,
      blockIds: p.blockIds,
      section: p.sectionTitle,
      sectionIndex: p.section,
      printedPage: p.page,
      excerpt: p.excerpt,
    );
    await showAppSheet(
      context,
      PassageReaderSheet(
        api: _readerApi,
        passage: passage,
        onTopic: (t) {
          Navigator.of(context).pop();
          _selectNode('t:${t.id}');
        },
        onAsk: widget.onResearch == null
            ? null
            : (prompt) {
                Navigator.of(context).pop();
                _research(prompt);
              },
      ),
      initialSize: 0.85,
    );
  }

  void _research(String prompt) {
    final cb = widget.onResearch;
    if (cb == null) return;
    Navigator.of(context).pop(); // close the graph; chat takes over
    cb(prompt);
  }

  // ── build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final m = _map;
    return PopScope(
      canPop: m == null || (_trail.isEmpty && _view == _View.overview),
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _goBack();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Row(children: [
            Icon(AppIcons.graph, color: theme.colorScheme.primary, size: 22),
            const SizedBox(width: AppSpacing.sm),
            const Flexible(child: Text('Knowledge Graph', overflow: TextOverflow.ellipsis)),
          ]),
          actions: [
            IconButton(tooltip: 'Whole library', icon: const Icon(Icons.public), onPressed: m == null ? null : _showOverview),
            IconButton(tooltip: 'How to use the graph', icon: const Icon(AppIcons.help), onPressed: () => _showHelp(context)),
          ],
        ),
        body: m == null
            ? (_building != null || _error != null
                ? BuildingView(status: _building?.message ?? '', progress: _building?.pct ?? 0, error: _error, onRetry: _loadMap)
                : const Center(child: CircularProgressIndicator()))
            : Column(children: [
                _searchBar(theme),
                if (_trail.isNotEmpty) _trailBar(theme),
                Expanded(
                  child: LayoutBuilder(builder: (context, c) {
                    final size = Size(c.maxWidth, c.maxHeight);
                    if (size != _viewport) {
                      final old = _viewport;
                      _viewport = size;
                      WidgetsBinding.instance.addPostFrameCallback((_) {
                        if (mounted) _onResize(old);
                      });
                    }
                    return Stack(children: [
                      Positioned.fill(child: _canvas(isDark)),
                      Positioned(
                        right: 12,
                        top: 10,
                        child: Column(children: [
                          _roundButton(Icons.add, () => _zoomBy(1.4), 'Zoom in'),
                          const SizedBox(height: 6),
                          _roundButton(Icons.remove, () => _zoomBy(0.7), 'Zoom out'),
                          const SizedBox(height: 6),
                          _roundButton(Icons.center_focus_strong, _fit, 'Fit'),
                        ]),
                      ),
                      if (size.width >= 600 && _view == _View.overview) Positioned(left: 12, top: 10, child: _legend(theme)),
                      DraggableScrollableSheet(
                        controller: _panel,
                        initialChildSize: 0.22,
                        minChildSize: 0.1,
                        maxChildSize: 0.92,
                        snap: true,
                        snapSizes: const [0.1, 0.22, 0.45, 0.6, 0.92],
                        builder: (context, scroll) => _panelBody(theme, scroll),
                      ),
                    ]);
                  }),
                ),
              ]),
      ),
    );
  }

  Widget _canvas(bool isDark) {
    // Keyboard navigation works once the canvas has focus (any click on it).
    return CallbackShortcuts(
      bindings: {
        const CharacterActivator('+'): () => _zoomBy(1.4),
        const CharacterActivator('='): () => _zoomBy(1.4),
        const SingleActivator(LogicalKeyboardKey.numpadAdd): () => _zoomBy(1.4),
        const CharacterActivator('-'): () => _zoomBy(0.7),
        const SingleActivator(LogicalKeyboardKey.numpadSubtract): () => _zoomBy(0.7),
        const CharacterActivator('0'): _fit,
        const SingleActivator(LogicalKeyboardKey.arrowLeft): () => _panBy(const Offset(120, 0)),
        const SingleActivator(LogicalKeyboardKey.arrowRight): () => _panBy(const Offset(-120, 0)),
        const SingleActivator(LogicalKeyboardKey.arrowUp): () => _panBy(const Offset(0, 120)),
        const SingleActivator(LogicalKeyboardKey.arrowDown): () => _panBy(const Offset(0, -120)),
        const SingleActivator(LogicalKeyboardKey.escape): _goBack,
      },
      child: Focus(
        focusNode: _canvasFocus,
        autofocus: true,
        child: Listener(
          onPointerDown: (_) => _canvasFocus.requestFocus(),
          child: _canvasBody(isDark),
        ),
      ),
    );
  }

  Widget _canvasBody(bool isDark) {
    final m = _map!;
    // Taps are caught outside the InteractiveViewer and converted to scene
    // coordinates (taps inside it were lost near the canvas edge on web).
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapUp: (d) => _onTap(d.localPosition),
      child: MouseRegion(
        onHover: (e) => _onHover(e.localPosition),
        onExit: (_) {
          if (_hovered != null) setState(() => _hovered = null);
        },
        cursor: _hovered != null ? SystemMouseCursors.click : SystemMouseCursors.grab,
        child: InteractiveViewer(
          transformationController: _tc,
          constrained: false,
          boundaryMargin: const EdgeInsets.all(double.infinity),
          minScale: _minScale,
          maxScale: _maxScale,
          // Gentler mouse-wheel zoom than the default 200 (≈1.3× per notch).
          scaleFactor: 400,
          onInteractionStart: (_) {
            _cam.stop();
            _fitted = false;
          },
          clipBehavior: Clip.hardEdge,
          child: SizedBox(
            width: kSceneSize,
            height: kSceneSize,
            child: RepaintBoundary(
              child: CustomPaint(
                painter: ConceptPainter(
                  map: m,
                  tc: _tc,
                  viewport: _viewport,
                  selected: _selected,
                  hovered: _hovered,
                  peers: _peerStrength,
                  emphasis: _emphasis,
                  isDark: isDark,
                  labels: _labels,
                  textScale: (_viewport.width / 1100).clamp(0.6, 1.0),
                  labelBudget: _viewport.width < 600 ? 120 : 240,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _searchBar(ThemeData theme) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        TextField(
          controller: _search,
          focusNode: _searchFocus,
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(
            hintText: 'Find an idea, a person, a saying, a book…',
            prefixIcon: IconButton(tooltip: 'Search', icon: const Icon(Icons.search), onPressed: () => _runSearch(_search.text)),
            isDense: true,
            suffixIcon: _search.text.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.clear),
                    onPressed: () {
                      _search.clear();
                      _onSearchChanged('');
                    },
                  ),
          ),
          onChanged: (v) {
            _debounce?.cancel();
            _debounce = Timer(const Duration(milliseconds: 120), () => _onSearchChanged(v));
            setState(() {});
          },
          onSubmitted: _runSearch,
        ),
        if (_suggestions.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: SizedBox(
              height: 34,
              child: ListView(scrollDirection: Axis.horizontal, children: [
                for (final n in _suggestions)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: _chip(theme, n.label, n.color, () {
                      _search.text = n.label;
                      _selectNode(n.id);
                    }),
                  ),
              ]),
            ),
          ),
      ]),
    );
  }

  Widget _trailBar(ThemeData theme) {
    return SizedBox(
      height: 38,
      child: ListView(
        scrollDirection: Axis.horizontal,
        reverse: false,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 4),
        children: [
          _chip(theme, 'Library', theme.colorScheme.onSurfaceVariant, _showOverview),
          for (var i = 0; i < _trail.length; i++) ...[
            Icon(Icons.chevron_right, size: 16, color: theme.colorScheme.onSurfaceVariant),
            _chip(theme, _trail[i].label, theme.colorScheme.primary, () => _goTo(i), selected: i == _trail.length - 1),
          ],
        ],
      ),
    );
  }

  Widget _legend(ThemeData theme) {
    final m = _map!;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface.withValues(alpha: 0.88),
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        for (final g in m.groups)
          InkWell(
            onTap: () => _filterGroup(_groupFilter == g.id ? null : g.id),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 1.5),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                GroupDot(g1.groupColor(g.id), size: 9),
                const SizedBox(width: 6),
                Text(g.label,
                    style: theme.textTheme.labelSmall?.copyWith(
                      fontWeight: _groupFilter == g.id ? FontWeight.w800 : FontWeight.w500,
                    )),
              ]),
            ),
          ),
      ]),
    );
  }

  // ── panel ────────────────────────────────────────────────────────────────

  Widget _panelBody(ThemeData theme, ScrollController scroll) {
    final children = <Widget>[
      Center(
        child: Container(
          width: 36,
          height: 4,
          margin: const EdgeInsets.only(top: 8, bottom: 6),
          decoration: BoxDecoration(color: theme.colorScheme.outlineVariant, borderRadius: BorderRadius.circular(2)),
        ),
      ),
      if (_loading) const LinearProgressIndicator(minHeight: 2),
      if (_panelError != null)
        Padding(padding: const EdgeInsets.all(AppSpacing.md), child: Text(_panelError!, style: TextStyle(color: theme.colorScheme.error))),
      ...switch (_view) {
        _View.overview => _overviewPanel(theme),
        _View.node => _nodePanel(theme),
        _View.meet => _meetPanel(theme),
        _View.book => _bookPanel(theme),
        _View.chapter => _chapterPanel(theme),
        _View.search => _searchPanel(theme),
      },
      const SizedBox(height: 40),
    ];
    return Material(
      color: theme.colorScheme.surface,
      elevation: 8,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(18))),
      clipBehavior: Clip.antiAlias,
      child: ListView(controller: scroll, padding: EdgeInsets.zero, children: children),
    );
  }

  EdgeInsets get _pad => const EdgeInsets.symmetric(horizontal: AppSpacing.md);

  List<Widget> _overviewPanel(ThemeData theme) {
    final m = _map!;
    final top = (List<ConceptNode>.from(m.nodes)..sort((a, b) => b.prominence.compareTo(a.prominence))).take(40);
    return [
      Padding(
        padding: _pad,
        child: Text('The whole library', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
      ),
      Padding(
        padding: _pad.copyWith(top: 4, bottom: 8),
        child: Text(
          '${_fmt(m.nodes.length)} ideas, people, places and sayings across ${m.books} books, '
          '${_fmt(m.chapters)} chapters and ${_fmt(m.passages)} passages. The biggest ones connect the most other ideas. '
          'Tap any of them, or zoom in to see more.',
          style: theme.textTheme.bodySmall,
        ),
      ),
      Padding(padding: _pad, child: Text('Most connected', style: theme.textTheme.labelLarge)),
      Padding(
        padding: _pad.copyWith(top: 6),
        child: Wrap(spacing: 6, runSpacing: 6, children: [
          for (final n in top) _chip(theme, n.label, n.color, () => _selectNode(n.id)),
        ]),
      ),
      if (_viewport.width < 600) ...[
        Padding(padding: _pad.copyWith(top: 14), child: Text('Themes', style: theme.textTheme.labelLarge)),
        Padding(
          padding: _pad.copyWith(top: 6),
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            for (final g in m.groups)
              _chip(theme, g.label, g1.groupColor(g.id), () => _filterGroup(_groupFilter == g.id ? null : g.id),
                  selected: _groupFilter == g.id),
          ]),
        ),
      ],
    ];
  }

  List<Widget> _nodePanel(ThemeData theme) {
    final m = _map!;
    if (_selected == null) return const [];
    final n = m.nodes[_selected!];
    final d = _detail;
    final header = Padding(
      padding: _pad,
      child: Row(children: [
        GroupDot(n.color, size: 12),
        const SizedBox(width: 8),
        Expanded(child: Text(n.label, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800))),
        if (widget.onResearch != null)
          TextButton.icon(
            icon: const Icon(Icons.travel_explore, size: 18),
            label: const Text('Research this'),
            onPressed: () => _research(
              'Research "${n.label}" across the literature: where it appears, how different books treat it, and how '
              'it connects to ${d != null && d.peers.isNotEmpty ? d.peers.take(3).map((p) => p.label).join(', ') : 'related ideas'}.',
            ),
          ),
      ]),
    );
    final sub = Padding(
      padding: _pad.copyWith(top: 2, bottom: 8),
      child: Text(
        [
          _typeLabel(n.type),
          '${_fmt(n.passages)} passages',
          if (d != null) 'in ${d.books.length} books',
          if (d != null) '${_fmt(d.peersTotal)} connected ideas',
        ].join(' · '),
        style: theme.textTheme.bodySmall,
      ),
    );
    if (d == null) return [header, sub];
    final tabs = Padding(
      padding: _pad.copyWith(bottom: 6),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SegmentedButton<int>(
          showSelectedIcon: false,
          segments: [
            ButtonSegment(value: 0, label: Text('Connected ${_fmt(d.peersTotal)}')),
            ButtonSegment(value: 1, label: Text('Books ${d.books.length}')),
            ButtonSegment(value: 2, label: Text('Chapters ${d.chapters.length}')),
            ButtonSegment(value: 3, label: Text('Passages')),
          ],
          selected: {_tab},
          onSelectionChanged: (s) => setState(() => _tab = s.first),
        ),
      ),
    );
    final body = switch (_tab) {
      0 => _peerList(theme, n, d),
      1 => [for (final b in d.books) _bookRow(theme, b)],
      2 => [for (final c in d.chapters) _chapterRow(theme, c)],
      _ => [for (final p in d.passages) _passageCard(theme, p)],
    };
    return [header, sub, tabs, ...body];
  }

  List<Widget> _peerList(ThemeData theme, ConceptNode n, NodeDetail d) {
    final shown = d.peers.take(_peerShown).toList();
    final maxW = d.peers.fold<double>(0.01, (a, p) => max(a, p.weight));
    return [
      Padding(
        padding: _pad.copyWith(bottom: 4),
        child: Text('Ideas that occur with ${n.label} more than chance — tap one to read where they meet.',
            style: theme.textTheme.bodySmall),
      ),
      for (final p in shown)
        InkWell(
          onTap: () => _openMeet(n.id, p.id),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 7),
            child: Row(children: [
              GroupDot(p.color, size: 9),
              const SizedBox(width: 8),
              Expanded(
                child: Semantics(
                  button: true,
                  label: 'Where ${n.label} meets ${p.label}: ${_fmt(p.shared)} passages',
                  onTap: () => _openMeet(n.id, p.id),
                  excludeSemantics: true,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(p.label, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 3),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(2),
                    child: LinearProgressIndicator(
                      value: (p.weight / maxW).clamp(0.02, 1.0),
                      minHeight: 3,
                      color: p.color,
                      backgroundColor: theme.colorScheme.surfaceContainerHighest,
                    ),
                  ),
                ]),
                ),
              ),
              const SizedBox(width: 10),
              Text('${_fmt(p.shared)} together', style: theme.textTheme.labelSmall),
              IconButton(
                tooltip: 'Go to ${p.label}',
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.arrow_forward, size: 18),
                onPressed: () => _selectNode(p.id),
              ),
            ]),
          ),
        ),
      if (_peerShown < d.peers.length || d.peers.length < d.peersTotal)
        Padding(
          padding: _pad,
          child: OutlinedButton(
            onPressed: () async {
              if (_peerShown < d.peers.length) {
                setState(() => _peerShown += 100);
              } else {
                final more = await _fetch(() => _api.node(n.id, peers: 800));
                if (more != null) {
                  setState(() {
                    _detail = more;
                    _peerShown += 100;
                  });
                }
              }
            },
            child: Text('Show more (${_fmt(d.peersTotal - min(_peerShown, d.peersTotal))} more)'),
          ),
        ),
    ];
  }

  List<Widget> _meetPanel(ThemeData theme) {
    final r = _meet;
    if (r == null) return [Padding(padding: _pad, child: const Text('Finding where they meet…'))];
    return [
      Padding(
        padding: _pad,
        child: Text.rich(
          TextSpan(children: [
            const TextSpan(text: 'Where '),
            TextSpan(text: r.a.label, style: TextStyle(color: r.a.color, fontWeight: FontWeight.w800)),
            const TextSpan(text: ' meets '),
            TextSpan(text: r.b.label, style: TextStyle(color: r.b.color, fontWeight: FontWeight.w800)),
          ]),
          style: theme.textTheme.titleMedium,
        ),
      ),
      Padding(
        padding: _pad.copyWith(top: 2, bottom: 6),
        child: Text('${_fmt(r.total)} passages mention both', style: theme.textTheme.bodySmall),
      ),
      Padding(
        padding: _pad.copyWith(bottom: 6),
        child: Wrap(spacing: 8, runSpacing: 6, children: [
          OutlinedButton(onPressed: () => _selectNode(r.a.id), child: Text('Go to ${r.a.label}')),
          OutlinedButton(onPressed: () => _selectNode(r.b.id), child: Text('Go to ${r.b.label}')),
          if (widget.onResearch != null)
            FilledButton.tonalIcon(
              icon: const Icon(Icons.travel_explore, size: 18),
              label: const Text('Research the connection'),
              onPressed: () => _research(
                  'How does the literature connect "${r.a.label}" and "${r.b.label}"? Compare how different books relate them.'),
            ),
        ]),
      ),
      for (final p in r.passages) _passageCard(theme, p),
      if (r.passages.length < r.total)
        Padding(padding: _pad, child: OutlinedButton(onPressed: _moreMeet, child: const Text('More passages'))),
    ];
  }

  List<Widget> _bookPanel(ThemeData theme) {
    final b = _book;
    if (b == null) return [Padding(padding: _pad, child: const Text('Opening the book…'))];
    return [
      Padding(padding: _pad, child: Text(b.book.title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800))),
      Padding(
        padding: _pad.copyWith(top: 2, bottom: 8),
        child: Text([if (b.book.author.isNotEmpty) b.book.author, b.book.categoryLabel].join(' · '),
            style: theme.textTheme.bodySmall),
      ),
      Padding(padding: _pad, child: Text('Ideas this book dwells on', style: theme.textTheme.labelLarge)),
      Padding(
        padding: _pad.copyWith(top: 6, bottom: 10),
        child: Wrap(spacing: 6, runSpacing: 6, children: [
          for (final c in b.concepts.take(90)) _chip(theme, c.label, c.color, () => _selectNode(c.id)),
        ]),
      ),
      Padding(padding: _pad, child: Text('Chapters', style: theme.textTheme.labelLarge)),
      for (final c in b.chapters) _chapterRow(theme, c, showBook: false),
    ];
  }

  List<Widget> _chapterPanel(ThemeData theme) {
    final c = _chapter;
    if (c == null) return [Padding(padding: _pad, child: const Text('Opening the chapter…'))];
    return [
      Padding(padding: _pad, child: Text(c.chapter.title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800))),
      Padding(
        padding: _pad.copyWith(top: 2, bottom: 6),
        child: InkWell(
          onTap: () => _openBook(c.book.id, c.book.title),
          child: Text('${c.book.title}${c.chapter.pages.isNotEmpty ? ' · ${c.chapter.pages}' : ''}  ›',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.primary)),
        ),
      ),
      Padding(padding: _pad, child: Text('Ideas in this chapter', style: theme.textTheme.labelLarge)),
      Padding(
        padding: _pad.copyWith(top: 6, bottom: 10),
        child: Wrap(spacing: 6, runSpacing: 6, children: [
          for (final n in c.concepts.take(80)) _chip(theme, n.label, n.color, () => _selectNode(n.id)),
        ]),
      ),
      if (widget.onResearch != null)
        Padding(
          padding: _pad.copyWith(bottom: 8),
          child: FilledButton.tonalIcon(
            icon: const Icon(Icons.travel_explore, size: 18),
            label: const Text('Research this chapter'),
            onPressed: () => _research('Read "${c.chapter.title}" in ${c.book.title} closely: what is its argument, its key '
                'passages, and how does it connect to the rest of the literature?'),
          ),
        ),
      Padding(padding: _pad, child: Text('Passages', style: theme.textTheme.labelLarge)),
      for (final p in c.passages) _passageCard(theme, p),
    ];
  }

  List<Widget> _searchPanel(ThemeData theme) {
    final r = _serverSearch;
    if (r == null) return [Padding(padding: _pad, child: const Text('Searching…'))];
    if (r.isEmpty) return [Padding(padding: _pad, child: const Text('Nothing matched. Try a shorter word.'))];
    return [
      if (r.nodes.isNotEmpty) ...[
        Padding(padding: _pad, child: Text('Ideas', style: theme.textTheme.labelLarge)),
        Padding(
          padding: _pad.copyWith(top: 6, bottom: 10),
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            for (final n in r.nodes) _chip(theme, n.label, n.color, () => _selectNode(n.id)),
          ]),
        ),
      ],
      if (r.books.isNotEmpty) ...[
        Padding(padding: _pad, child: Text('Books', style: theme.textTheme.labelLarge)),
        for (final b in r.books) _bookRow(theme, b),
      ],
      if (r.chapters.isNotEmpty) ...[
        Padding(padding: _pad.copyWith(top: 8), child: Text('Chapters', style: theme.textTheme.labelLarge)),
        for (final c in r.chapters) _chapterRow(theme, c),
      ],
    ];
  }

  // ── rows ─────────────────────────────────────────────────────────────────

  Widget _bookRow(ThemeData theme, BookRef b) => ListTile(
        dense: true,
        leading: const Icon(Icons.menu_book_outlined, size: 20),
        title: Text(b.title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text([if (b.author.isNotEmpty) b.author, if (b.categoryLabel.isNotEmpty) b.categoryLabel].join(' · ')),
        trailing: b.count > 0 ? Text('${_fmt(b.count)}×', style: theme.textTheme.labelMedium) : null,
        onTap: () => _openBook(b.id, b.title),
      );

  Widget _chapterRow(ThemeData theme, ChapterRef c, {bool showBook = true}) => ListTile(
        dense: true,
        leading: const Icon(Icons.bookmark_border, size: 20),
        title: Text(c.title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text([if (showBook) c.bookTitle, if (c.pages.isNotEmpty) c.pages].join(' · ')),
        trailing: c.count > 0 ? Text('${_fmt(c.count)}×', style: theme.textTheme.labelMedium) : null,
        onTap: () => _openChapter(c.docId, c.section, c.title),
      );

  Widget _passageCard(ThemeData theme, CPassage p) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 5),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
          onTap: () => _openPassage(p),
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerLow,
              borderRadius: BorderRadius.circular(AppSpacing.radius),
              border: Border.all(color: theme.colorScheme.outlineVariant),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p.where, style: theme.textTheme.labelMedium?.copyWith(color: theme.colorScheme.primary, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text(p.excerpt, style: theme.textTheme.bodySmall?.copyWith(height: 1.4)),
            ]),
          ),
        ),
      );

  Widget _chip(ThemeData theme, String label, Color color, VoidCallback onTap, {bool selected = false}) => ActionChip(
        avatar: GroupDot(color, size: 8),
        label: Text(label),
        visualDensity: VisualDensity.compact,
        side: BorderSide(color: selected ? color : theme.colorScheme.outlineVariant, width: selected ? 1.6 : 1),
        onPressed: onTap,
      );

  Widget _roundButton(IconData icon, VoidCallback onTap, String tooltip) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surface.withValues(alpha: 0.9),
      shape: CircleBorder(side: BorderSide(color: theme.colorScheme.outlineVariant)),
      child: IconButton(icon: Icon(icon, size: 20), tooltip: tooltip, onPressed: onTap),
    );
  }

  void _showHelp(BuildContext context) {
    showAppSheet(
      context,
      const Padding(
        padding: EdgeInsets.all(AppSpacing.lg),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text('How to use the graph', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          SizedBox(height: 12),
          Text('• Every dot is an idea, person, place, saying or practice found in the books. Bigger dots connect more of '
              'the other ideas.'),
          SizedBox(height: 6),
          Text('• Tap one to see everything it connects to, and the books, chapters and passages where it appears.'),
          SizedBox(height: 6),
          Text('• Tap a connected idea to read the passages where the two meet. From any book or chapter, tap an idea to '
              'keep going.'),
          SizedBox(height: 6),
          Text('• "Research this" asks the app to read the books and write a cited answer about it.'),
          SizedBox(height: 6),
          Text('• Keyboard: + and − zoom, 0 fits the whole map, the arrow keys move around, Esc goes back.'),
        ]),
      ),
      fitContent: true,
    );
  }
}

String _typeLabel(String t) => switch (t) {
      'topic' => 'Theme',
      'person' => 'Person',
      'place' => 'Place',
      'organization' => 'Organization',
      'text' => 'Book or text',
      'saying' => 'Saying',
      'prayer' => 'Prayer',
      'practice' => 'Practice',
      'emotion' => 'Feeling',
      'trait' => 'Trait',
      'event' => 'Event',
      'substance' => 'Substance',
      'condition' => 'Condition',
      _ => 'Idea',
    };

String _fmt(int n) {
  final s = n.toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
    b.write(s[i]);
  }
  return b.toString();
}
