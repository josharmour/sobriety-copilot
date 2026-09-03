/// Canvas painter for the knowledge graph.
///
/// Draws edges (weighted, highlighted around the selected node), topic nodes
/// as group-coloured discs, book nodes as rounded "spine" cards, and labels.
/// Positions are supplied already interpolated so the screen can animate
/// between layouts.
library;

import 'dart:math';

import 'package:flutter/material.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

import 'graph_layout.dart';
import 'graph_models.dart';

class GraphPainter extends CustomPainter {
  final GraphLayout layout;
  final Map<String, Offset> positions;
  final String? selectedId;
  final String? hoveredId;
  final Set<String> highlightIds;
  final bool isDark;
  final double scale; // current viewer zoom, so labels stay legible

  static final Map<String, TextPainter> _textCache = {};

  GraphPainter({
    required this.layout,
    required this.positions,
    required this.selectedId,
    required this.hoveredId,
    required this.highlightIds,
    required this.isDark,
    required this.scale,
  });

  Color get _edgeBase => isDark ? Colors.white : AppColors.brand;
  Color get _labelColor => isDark ? AppColors.darkText : AppColors.lightText;
  Color get _labelHalo => isDark ? AppColors.darkBg : AppColors.lightBg;

  @override
  void paint(Canvas canvas, Size size) {
    _paintEdges(canvas);
    for (final entry in positions.entries) {
      final node = layout.nodes[entry.key];
      if (node == null) continue;
      if (node.kind == 'book') {
        _paintBook(canvas, node, entry.value);
      } else {
        _paintTopic(canvas, node, entry.value);
      }
    }
  }

  void _paintEdges(Canvas canvas) {
    final focusId = selectedId ?? hoveredId;
    for (final e in layout.edges) {
      final a = positions[e.a];
      final b = positions[e.b];
      if (a == null || b == null) continue;
      final na = layout.nodes[e.a];
      final nb = layout.nodes[e.b];
      final touchesFocus = focusId != null && (e.a == focusId || e.b == focusId);
      final dimmed = (na?.dimmed ?? false) || (nb?.dimmed ?? false);
      final w = e.weight.clamp(0.0, 1.0);
      Color color;
      double width;
      if (touchesFocus) {
        color = AppColors.accent.withValues(alpha: 0.55 + 0.45 * w);
        width = 1.6 + 3.2 * w;
      } else {
        final alpha = dimmed ? 0.04 : (isDark ? 0.10 + 0.30 * w : 0.08 + 0.28 * w);
        color = _edgeBase.withValues(alpha: alpha);
        width = 0.8 + 2.4 * w;
      }
      final paint = Paint()
        ..color = color
        ..strokeWidth = width
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round;
      // Slight curve so overlapping edges are distinguishable.
      final mid = Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2);
      final dir = b - a;
      final normal = Offset(-dir.dy, dir.dx) / max(dir.distance, 1);
      final ctrl = mid + normal * min(dir.distance * 0.12, 40);
      final path = Path()
        ..moveTo(a.dx, a.dy)
        ..quadraticBezierTo(ctrl.dx, ctrl.dy, b.dx, b.dy);
      canvas.drawPath(path, paint);
    }
  }

  void _paintTopic(Canvas canvas, LayoutNode node, Offset p) {
    final color = groupColor(node.group);
    final selected = node.id == selectedId;
    final hovered = node.id == hoveredId;
    final highlighted = highlightIds.contains(node.id);
    final alpha = node.dimmed ? 0.25 : 1.0;
    final r = node.radius * (selected ? 1.12 : 1.0);

    if (selected || highlighted) {
      canvas.drawCircle(
        p,
        r + 9,
        Paint()..color = AppColors.accent.withValues(alpha: selected ? 0.28 : 0.16),
      );
    }
    // Soft glow so discs read on both surfaces.
    canvas.drawCircle(p, r + 3, Paint()..color = color.withValues(alpha: 0.18 * alpha));
    canvas.drawCircle(p, r, Paint()..color = color.withValues(alpha: alpha));
    canvas.drawCircle(
      p,
      r,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = selected ? 3 : (hovered ? 2.2 : 1.2)
        ..color = (selected || hovered ? AppColors.accent : (isDark ? Colors.white : AppColors.brand))
            .withValues(alpha: (selected || hovered ? 1.0 : 0.55) * alpha),
    );
    if (node.isFocus) {
      // Inner ring marks the current focus.
      canvas.drawCircle(
        p,
        r * 0.55,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = Colors.white.withValues(alpha: 0.85),
      );
    }
    _paintLabel(canvas, node.label, p + Offset(0, r + 6), alpha, bold: selected || node.isFocus,
        maxWidth: node.isFocus ? 220 : 150);
  }

  void _paintBook(Canvas canvas, LayoutNode node, Offset p) {
    final alpha = node.dimmed ? 0.3 : 1.0;
    final selected = node.id == selectedId;
    final hovered = node.id == hoveredId;
    final w = 34.0 + 30.0 * node.weight;
    final h = 46.0 + 22.0 * node.weight;
    final rect = Rect.fromCenter(center: p, width: w, height: h);
    final rrect = RRect.fromRectAndRadius(rect, const Radius.circular(6));
    final fill = isDark ? const Color(0xFF1C2A3D) : Colors.white;
    final spine = _categoryColor(node.group);
    if (selected || highlightIds.contains(node.id)) {
      canvas.drawRRect(
        rrect.inflate(7),
        Paint()..color = AppColors.accent.withValues(alpha: selected ? 0.28 : 0.16),
      );
    }
    canvas.drawRRect(rrect.shift(const Offset(2, 3)), Paint()..color = Colors.black.withValues(alpha: 0.18 * alpha));
    canvas.drawRRect(rrect, Paint()..color = fill.withValues(alpha: alpha));
    // Spine stripe on the left, coloured by category.
    canvas.drawRRect(
      RRect.fromRectAndCorners(
        Rect.fromLTWH(rect.left, rect.top, 7, rect.height),
        topLeft: const Radius.circular(6),
        bottomLeft: const Radius.circular(6),
      ),
      Paint()..color = spine.withValues(alpha: alpha),
    );
    canvas.drawRRect(
      rrect,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = selected ? 2.6 : (hovered ? 2 : 1)
        ..color = (selected || hovered ? AppColors.accent : (isDark ? Colors.white : AppColors.brand))
            .withValues(alpha: (selected || hovered ? 1.0 : 0.35) * alpha),
    );
    // Page lines.
    final line = Paint()
      ..color = (isDark ? Colors.white : AppColors.brand).withValues(alpha: 0.18 * alpha)
      ..strokeWidth = 1;
    for (var y = rect.top + 12; y < rect.bottom - 8; y += 7) {
      canvas.drawLine(Offset(rect.left + 13, y), Offset(rect.right - 6, y), line);
    }
    _paintLabel(canvas, node.label, Offset(p.dx, rect.bottom + 5), alpha, bold: selected, maxWidth: 140);
  }

  Color _categoryColor(String category) {
    switch (category) {
      case 'conference_approved':
        return AppColors.gold;
      case 'books_about_aa':
        return AppColors.accent;
      case 'related_nonfiction':
        return const Color(0xFF9B5DE5);
      default:
        return const Color(0xFF4CAF50);
    }
  }

  void _paintLabel(Canvas canvas, String text, Offset topCenter, double alpha,
      {bool bold = false, double maxWidth = 150}) {
    // Keep labels readable when zoomed out; cap growth when zoomed in.
    final fontSize = (12.5 / scale).clamp(11.0, 26.0);
    final key = '$text|$bold|${fontSize.toStringAsFixed(1)}|$maxWidth|$isDark';
    var tp = _textCache[key];
    if (tp == null) {
      tp = TextPainter(
        text: TextSpan(
          text: text,
          style: TextStyle(
            fontSize: fontSize,
            fontWeight: bold ? FontWeight.w700 : FontWeight.w600,
            color: _labelColor,
            height: 1.15,
          ),
        ),
        textAlign: TextAlign.center,
        textDirection: TextDirection.ltr,
        maxLines: 2,
        ellipsis: '…',
      )..layout(maxWidth: maxWidth);
      if (_textCache.length > 600) _textCache.clear();
      _textCache[key] = tp;
    }
    final offset = Offset(topCenter.dx - tp.width / 2, topCenter.dy);
    // Halo behind the text so it stays legible over edges.
    final bg = Rect.fromLTWH(offset.dx - 4, offset.dy - 1, tp.width + 8, tp.height + 2);
    canvas.drawRRect(
      RRect.fromRectAndRadius(bg, const Radius.circular(5)),
      Paint()..color = _labelHalo.withValues(alpha: 0.72 * alpha),
    );
    canvas.saveLayer(bg.inflate(2), Paint()..color = Colors.white.withValues(alpha: alpha));
    tp.paint(canvas, offset);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant GraphPainter old) =>
      old.positions != positions ||
      old.layout != layout ||
      old.selectedId != selectedId ||
      old.hoveredId != hoveredId ||
      old.highlightIds != highlightIds ||
      old.isDark != isDark ||
      old.scale != scale;
}

/// Hit-test helper shared by tap and hover handling.
String? hitTestNode(GraphLayout layout, Map<String, Offset> positions, Offset p) {
  String? best;
  var bestD = double.infinity;
  positions.forEach((id, pos) {
    final node = layout.nodes[id];
    if (node == null) return;
    final d = (pos - p).distance;
    final reach = node.kind == 'book' ? 40.0 + 18.0 * node.weight : node.radius + 14;
    if (d <= reach && d < bestD) {
      best = id;
      bestD = d;
    }
  });
  return best;
}
