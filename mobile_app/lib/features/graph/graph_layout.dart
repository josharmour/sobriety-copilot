/// Layout engines for the knowledge graph canvas.
///
/// * [forceLayout] — a Fruchterman–Reingold style force-directed layout with
///   a gentle pull toward each group's cluster centre, used for the overview.
/// * [radialLayout] — concentric rings around a focus node, used when a topic
///   or a book is in focus.
library;

import 'dart:math';

import 'package:flutter/material.dart';

/// A positioned, drawable node on the canvas.
class LayoutNode {
  final String id;
  final String kind; // 'topic' | 'book'
  final String label;
  final String group; // taxonomy group (topics) or category (books)
  final double radius;
  final double weight; // 0..1 emphasis (edge strength to the focus)
  final bool isFocus;
  final bool dimmed;

  const LayoutNode({
    required this.id,
    required this.kind,
    required this.label,
    required this.group,
    required this.radius,
    this.weight = 1,
    this.isFocus = false,
    this.dimmed = false,
  });

  LayoutNode copyWith({bool? dimmed}) => LayoutNode(
        id: id,
        kind: kind,
        label: label,
        group: group,
        radius: radius,
        weight: weight,
        isFocus: isFocus,
        dimmed: dimmed ?? this.dimmed,
      );
}

class LayoutEdge {
  final String a;
  final String b;
  final double weight; // 0..1
  const LayoutEdge(this.a, this.b, this.weight);
}

class GraphLayout {
  final Map<String, LayoutNode> nodes;
  final List<LayoutEdge> edges;
  final Map<String, Offset> positions;
  const GraphLayout({required this.nodes, required this.edges, required this.positions});

  Rect get bounds {
    if (positions.isEmpty) return Rect.zero;
    var minX = double.infinity, minY = double.infinity, maxX = -double.infinity, maxY = -double.infinity;
    positions.forEach((id, p) {
      final r = nodes[id]?.radius ?? 20;
      minX = min(minX, p.dx - r - 60);
      maxX = max(maxX, p.dx + r + 60);
      minY = min(minY, p.dy - r - 40);
      maxY = max(maxY, p.dy + r + 40);
    });
    return Rect.fromLTRB(minX, minY, maxX, maxY);
  }
}

/// Force-directed overview. Deterministic for a given input (seeded RNG) so
/// the map looks the same every time it opens.
GraphLayout forceLayout({
  required List<LayoutNode> nodes,
  required List<LayoutEdge> edges,
  required List<String> groupOrder,
  int iterations = 320,
  double area = 1400,
}) {
  final rng = Random(7);
  final ids = nodes.map((n) => n.id).toList();
  final index = {for (var i = 0; i < ids.length; i++) ids[i]: i};
  final n = ids.length;
  if (n == 0) {
    return const GraphLayout(nodes: {}, edges: [], positions: {});
  }
  final pos = List<Offset>.filled(n, Offset.zero);
  final center = Offset(area / 2, area / 2);

  // Seed each group on its own wedge of a circle so clusters start apart.
  final groupAngle = <String, double>{};
  for (var i = 0; i < groupOrder.length; i++) {
    groupAngle[groupOrder[i]] = 2 * pi * i / max(groupOrder.length, 1);
  }
  final groupCenter = <String, Offset>{};
  groupAngle.forEach((g, a) {
    groupCenter[g] = center + Offset(cos(a), sin(a)) * (area * 0.28);
  });
  for (var i = 0; i < n; i++) {
    final g = nodes[i].group;
    final c = groupCenter[g] ?? center;
    pos[i] = c + Offset(rng.nextDouble() - 0.5, rng.nextDouble() - 0.5) * (area * 0.18);
  }

  final k = sqrt(area * area / n) * 0.62; // ideal edge length
  final adj = <List<(int, double)>>[for (var i = 0; i < n; i++) <(int, double)>[]];
  for (final e in edges) {
    final a = index[e.a], b = index[e.b];
    if (a == null || b == null || a == b) continue;
    adj[a].add((b, e.weight));
    adj[b].add((a, e.weight));
  }

  final disp = List<Offset>.filled(n, Offset.zero);
  var temperature = area / 8;
  for (var it = 0; it < iterations; it++) {
    for (var i = 0; i < n; i++) {
      disp[i] = Offset.zero;
    }
    // Repulsion (all pairs).
    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        var delta = pos[i] - pos[j];
        var d = delta.distance;
        if (d < 0.01) {
          delta = Offset(rng.nextDouble() - 0.5, rng.nextDouble() - 0.5);
          d = delta.distance;
        }
        final minGap = nodes[i].radius + nodes[j].radius + 34;
        var force = (k * k) / d;
        if (d < minGap) force *= 2.5; // hard-ish collision push
        final v = delta / d * force;
        disp[i] += v;
        disp[j] -= v;
      }
    }
    // Attraction along edges (stronger for stronger relationships).
    for (var i = 0; i < n; i++) {
      for (final (j, w) in adj[i]) {
        if (j < i) continue;
        final delta = pos[i] - pos[j];
        final d = max(delta.distance, 0.01);
        final force = (d * d / k) * (0.35 + w);
        final v = delta / d * force;
        disp[i] -= v;
        disp[j] += v;
      }
    }
    // Gravity toward group centre + global centre keeps clusters legible.
    for (var i = 0; i < n; i++) {
      final gc = groupCenter[nodes[i].group] ?? center;
      disp[i] += (gc - pos[i]) * 0.045;
      disp[i] += (center - pos[i]) * 0.012;
    }
    for (var i = 0; i < n; i++) {
      final d = disp[i].distance;
      if (d > 0) {
        pos[i] += disp[i] / d * min(d, temperature);
      }
    }
    temperature = max(temperature * 0.96, 2.0);
  }

  return GraphLayout(
    nodes: {for (final node in nodes) node.id: node},
    edges: edges,
    positions: {for (var i = 0; i < n; i++) ids[i]: pos[i]},
  );
}

/// Rings around [focus]: [ring1] on the inner ring, [ring2] on the outer ring.
/// Nodes on a ring are spread by their order; both rings are offset so they
/// interleave instead of lining up radially.
GraphLayout radialLayout({
  required LayoutNode focus,
  required List<LayoutNode> ring1,
  required List<LayoutNode> ring2,
  required List<LayoutEdge> edges,
  double innerRadius = 250,
  double outerRadius = 470,
  Offset center = const Offset(700, 700),
}) {
  final positions = <String, Offset>{focus.id: center};
  void place(List<LayoutNode> ring, double radius, double phase) {
    if (ring.isEmpty) return;
    // Enough room for every label: grow the radius when a ring is crowded.
    final needed = ring.length * 120 / (2 * pi);
    final r = max(radius, needed);
    for (var i = 0; i < ring.length; i++) {
      final a = -pi / 2 + phase + 2 * pi * i / ring.length;
      positions[ring[i].id] = center + Offset(cos(a), sin(a)) * r;
    }
  }

  place(ring1, innerRadius, 0);
  place(ring2, outerRadius, ring2.isEmpty ? 0 : pi / ring2.length);
  final nodes = <String, LayoutNode>{focus.id: focus};
  for (final n in ring1) {
    nodes[n.id] = n;
  }
  for (final n in ring2) {
    nodes[n.id] = n;
  }
  return GraphLayout(nodes: nodes, edges: edges, positions: positions);
}
