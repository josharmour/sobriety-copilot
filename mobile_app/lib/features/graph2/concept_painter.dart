/// Paints thousands of concepts as a word-cloud map.
///
/// * Positions come from the server (a precomputed 2-D map in 0..1).
/// * Size follows prominence — how many other ideas a concept bridges.
/// * Labels are placed most-prominent-first at a size that follows
///   prominence, skipping any that would overlap one already placed; zooming
///   in leaves room for more, so the cloud fills in as you go.
/// * With a concept selected, lines run to its strongest peers and everything
///   else fades back.
///
/// The painter repaints on the transformation controller, so pan/zoom never
/// rebuilds widgets; text layouts are cached across frames in [LabelCache].
library;

import 'dart:math';

import 'package:flutter/material.dart';

import 'concept_models.dart';

const double kSceneSize = 3200;
const double _pad = 140;

Offset scenePos(ConceptNode n) => Offset(_pad + n.x * (kSceneSize - 2 * _pad), _pad + n.y * (kSceneSize - 2 * _pad));

/// Node radius in scene units at a zoom level: grows only gently on screen as you zoom in.
double nodeRadius(ConceptNode n, double zoom) => (1.6 + 15 * sqrt(n.prominence)) / pow(zoom, 0.6);

class LabelCache {
  final Map<int, TextPainter> _cache = {};
  int _theme = 0;

  /// Scene-space rectangles of the labels painted last frame (for tap hit-testing).
  final Map<int, Rect> placed = {};

  TextPainter get(int key, String text, double fontSize, Color color, FontWeight weight, bool isDark) {
    final themeKey = isDark ? 1 : 2;
    if (themeKey != _theme) {
      _cache.clear();
      _theme = themeKey;
    }
    final k = key * 1000 + (fontSize * 4).round() * 4 + (weight.value ~/ 100) % 4;
    final hit = _cache[k];
    if (hit != null && hit.text is TextSpan && (hit.text as TextSpan).style?.color == color) return hit;
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(
          fontSize: fontSize,
          color: color,
          fontWeight: weight,
          height: 1.0,
          shadows: [Shadow(color: isDark ? Colors.black : Colors.white, blurRadius: 3)],
        ),
      ),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout(maxWidth: 420);
    if (_cache.length > 4000) _cache.clear();
    _cache[k] = tp;
    return tp;
  }
}

class ConceptPainter extends CustomPainter {
  final ConceptMap map;
  final TransformationController tc;
  final Size viewport;
  final int? selected;
  final int? hovered;
  final Map<int, double> peers; // peer index -> strength 0..1 (when a node is selected)
  final Set<int> emphasis; // e.g. search hits / a group filter
  final bool isDark;
  final LabelCache labels;
  final int labelBudget;

  /// Shrinks label type on small screens (1.0 on a desktop-width canvas).
  final double textScale;

  ConceptPainter({
    required this.map,
    required this.tc,
    required this.viewport,
    required this.selected,
    required this.hovered,
    required this.peers,
    required this.emphasis,
    required this.isDark,
    required this.labels,
    this.labelBudget = 240,
    this.textScale = 1.0,
  }) : super(repaint: tc);

  @override
  void paint(Canvas canvas, Size size) {
    final m = tc.value;
    final zoom = m.getMaxScaleOnAxis();
    final inv = Matrix4.inverted(m);
    final tl = MatrixUtils.transformPoint(inv, Offset.zero);
    final br = MatrixUtils.transformPoint(inv, Offset(viewport.width, viewport.height));
    final visible = Rect.fromPoints(tl, br).inflate(60 / zoom);
    final focus = selected != null;
    final filtering = emphasis.isNotEmpty;
    final bg = isDark ? const Color(0xFF0F1418) : const Color(0xFFF7F8FA);
    final textColor = isDark ? const Color(0xFFE8EDF2) : const Color(0xFF1C2329);
    final dimText = isDark ? const Color(0x88E8EDF2) : const Color(0x881C2329);

    // Lines to the selected node's peers.
    if (focus) {
      final s = map.nodes[selected!];
      final ps = scenePos(s);
      final line = Paint()..strokeWidth = 1.2 / zoom;
      final ordered = peers.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
      for (final e in ordered.take(160)) {
        final p = map.nodes[e.key];
        line.color = s.color.withValues(alpha: 0.10 + 0.55 * e.value);
        canvas.drawLine(ps, scenePos(p), line);
      }
    }

    // Dots.
    final dot = Paint();
    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2 / zoom;
    for (final n in map.nodes) {
      final p = scenePos(n);
      if (!visible.contains(p)) continue;
      final r = nodeRadius(n, zoom);
      final lit = !focus && !filtering ||
          n.index == selected ||
          peers.containsKey(n.index) ||
          (filtering && emphasis.contains(n.index));
      dot.color = lit ? n.color.withValues(alpha: n.isTopic ? 0.95 : 0.82) : n.color.withValues(alpha: 0.12);
      canvas.drawCircle(p, r, dot);
      if (n.isTopic && lit) {
        ring.color = bg.withValues(alpha: 0.9);
        canvas.drawCircle(p, r, ring);
      }
    }
    if (focus) {
      final s = map.nodes[selected!];
      ring.color = textColor;
      canvas.drawCircle(scenePos(s), nodeRadius(s, zoom) + 4 / zoom, ring);
    }

    // Labels: most important first, skip overlaps (screen space).
    labels.placed.clear();
    final order = <int>[];
    if (selected != null) order.add(selected!);
    if (hovered != null && hovered != selected) order.add(hovered!);
    if (focus) {
      final ps = peers.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
      order.addAll(ps.map((e) => e.key));
    }
    if (filtering) {
      final es = emphasis.toList()..sort((a, b) => map.nodes[b].prominence.compareTo(map.nodes[a].prominence));
      order.addAll(es);
    }
    order.addAll(_byProminence());
    final grid = <int, List<Rect>>{};
    const cell = 80.0;
    bool collides(Rect r) {
      final x0 = (r.left / cell).floor(), x1 = (r.right / cell).floor();
      final y0 = (r.top / cell).floor(), y1 = (r.bottom / cell).floor();
      for (var x = x0; x <= x1; x++) {
        for (var y = y0; y <= y1; y++) {
          for (final o in grid[x * 100003 + y] ?? const <Rect>[]) {
            if (o.overlaps(r)) return true;
          }
        }
      }
      return false;
    }

    void occupy(Rect r) {
      final x0 = (r.left / cell).floor(), x1 = (r.right / cell).floor();
      final y0 = (r.top / cell).floor(), y1 = (r.bottom / cell).floor();
      for (var x = x0; x <= x1; x++) {
        for (var y = y0; y <= y1; y++) {
          (grid[x * 100003 + y] ??= []).add(r);
        }
      }
    }

    var budget = labelBudget + (focus ? 80 : 0);
    final seen = <int>{};
    for (final i in order) {
      if (budget <= 0) break;
      if (!seen.add(i)) continue;
      final n = map.nodes[i];
      final p = scenePos(n);
      if (!visible.contains(p)) continue;
      final isSel = i == selected;
      final isPeer = peers.containsKey(i);
      final lit = !focus && !filtering || isSel || isPeer || emphasis.contains(i) || i == hovered;
      if (!lit && (focus || filtering)) continue;
      // Screen font size: big for prominent ideas, readable floor for the rest.
      var fs = 9.5 + 20 * pow(n.prominence, 0.55);
      if (isSel) fs = max(fs, 18);
      if (isPeer) fs = max(fs * 0.9, 11 + 6 * (peers[i] ?? 0));
      fs = max(9.0, fs * textScale);
      final weight = isSel || n.isTopic || n.prominence > 0.35 ? FontWeight.w700 : FontWeight.w500;
      final color = lit ? (n.isTopic || isSel ? textColor : Color.lerp(textColor, n.color, 0.35)!) : dimText;
      final tp = labels.get(i, n.label, fs, color, weight, isDark);
      final screen = MatrixUtils.transformPoint(m, p);
      final r = nodeRadius(n, zoom) * zoom;
      final box = Rect.fromLTWH(screen.dx - tp.width / 2, screen.dy + r + 1, tp.width, tp.height).inflate(1.5);
      if (!isSel && i != hovered && collides(box)) continue;
      occupy(box);
      budget--;
      // Draw in screen space so text stays crisp at any zoom.
      canvas.save();
      canvas.transform(inv.storage);
      tp.paint(canvas, Offset(box.left + 1.5, box.top + 1.5));
      canvas.restore();
      labels.placed[i] = Rect.fromPoints(MatrixUtils.transformPoint(inv, box.topLeft), MatrixUtils.transformPoint(inv, box.bottomRight));
    }
  }

  List<int>? _sorted;
  List<int> _byProminence() =>
      _sorted ??= (List<int>.generate(map.nodes.length, (i) => i)
        ..sort((a, b) => map.nodes[b].prominence.compareTo(map.nodes[a].prominence)));

  @override
  bool shouldRepaint(covariant ConceptPainter old) =>
      old.map != map ||
      old.selected != selected ||
      old.hovered != hovered ||
      old.peers != peers ||
      old.emphasis != emphasis ||
      old.isDark != isDark ||
      old.viewport != viewport ||
      old.textScale != textScale;
}

/// The node under a scene point: a label or a dot (generous on touch screens).
int? hitTestConcept(ConceptMap map, Offset scene, double zoom, LabelCache labels, {Map<int, double>? prefer}) {
  for (final e in labels.placed.entries) {
    if (e.value.inflate(2 / zoom).contains(scene)) return e.key;
  }
  int? best;
  var bestD = double.infinity;
  final slop = 14 / zoom;
  for (final n in map.nodes) {
    final p = scenePos(n);
    final dx = (p.dx - scene.dx).abs(), dy = (p.dy - scene.dy).abs();
    final r = nodeRadius(n, zoom) + slop;
    if (dx > r || dy > r) continue;
    var d = sqrt(dx * dx + dy * dy) - nodeRadius(n, zoom);
    if (prefer != null && prefer.isNotEmpty && !prefer.containsKey(n.index)) d += slop; // favour lit nodes
    if (d < bestD && d <= slop) {
      bestD = d;
      best = n.index;
    }
  }
  return best;
}
