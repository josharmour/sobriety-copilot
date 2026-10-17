/// Data for the concept graph (`/api/graph2/*`, see `src/rag/concept_graph.py`).
library;

import 'dart:ui';

import 'package:sobriety_copilot_mobile/features/graph/graph_models.dart' show groupColor;

int _int(dynamic v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
double _dbl(dynamic v) => v is num ? v.toDouble() : double.tryParse('$v') ?? 0.0;
String _str(dynamic v) => v?.toString() ?? '';
List<Map<String, dynamic>> _maps(dynamic v) => (v as List<dynamic>? ?? const []).whereType<Map<String, dynamic>>().toList();

/// Node types that read better with their own colour than their topic's.
const Map<String, Color> kTypeColors = {
  'person': Color(0xFFE0A458),
  'place': Color(0xFF6FB3B8),
  'organization': Color(0xFF8E9AAF),
  'text': Color(0xFFB39DDB),
  'prayer': Color(0xFFF2C14E),
  'saying': Color(0xFFF28F6B),
};

class ConceptNode {
  final int index;
  final String id;
  final String label;
  final String type;
  final String group;
  final double x;
  final double y;
  final double prominence;
  final int passages;
  final List<int> topPeers;

  const ConceptNode({
    required this.index,
    required this.id,
    required this.label,
    required this.type,
    required this.group,
    required this.x,
    required this.y,
    required this.prominence,
    required this.passages,
    required this.topPeers,
  });

  bool get isTopic => id.startsWith('t:');
  Color get color => kTypeColors[type] ?? groupColor(group);
}

class ConceptGroup {
  final String id;
  final String label;
  const ConceptGroup(this.id, this.label);
}

class ConceptMap {
  final List<ConceptNode> nodes;
  final Map<String, int> index;
  final List<ConceptGroup> groups;
  final int passages;
  final int books;
  final int chapters;

  ConceptMap({required this.nodes, required this.groups, required this.passages, required this.books, required this.chapters})
      : index = {for (final n in nodes) n.id: n.index};

  ConceptNode? byId(String id) {
    final i = index[id];
    return i == null ? null : nodes[i];
  }

  factory ConceptMap.fromJson(Map<String, dynamic> j) {
    final fields = (j['fields'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList();
    int f(String name) => fields.indexOf(name);
    final iId = f('id'), iLabel = f('label'), iType = f('type'), iGroup = f('group');
    final iX = f('x'), iY = f('y'), iProm = f('prominence'), iPass = f('passages'), iPeers = f('top_peers');
    final rows = j['nodes'] as List<dynamic>? ?? const [];
    final nodes = <ConceptNode>[];
    for (var i = 0; i < rows.length; i++) {
      final r = rows[i] as List<dynamic>;
      nodes.add(ConceptNode(
        index: i,
        id: _str(r[iId]),
        label: _str(r[iLabel]),
        type: _str(r[iType]),
        group: _str(r[iGroup]),
        x: _dbl(r[iX]),
        y: _dbl(r[iY]),
        prominence: _dbl(r[iProm]),
        passages: _int(r[iPass]),
        topPeers: iPeers >= 0 ? (r[iPeers] as List<dynamic>? ?? const []).map(_int).toList() : const [],
      ));
    }
    final stats = j['stats'] as Map<String, dynamic>? ?? const {};
    return ConceptMap(
      nodes: nodes,
      groups: [for (final g in _maps(j['groups'])) ConceptGroup(_str(g['id']), _str(g['label']))],
      passages: _int(stats['passages']),
      books: _int(stats['books']),
      chapters: _int(stats['chapters']),
    );
  }
}

class NodeRef {
  final String id;
  final String label;
  final String type;
  final String group;
  final int passages;
  final double weight;
  final int shared;
  final int count;

  const NodeRef({
    required this.id,
    required this.label,
    this.type = 'concept',
    this.group = 'other',
    this.passages = 0,
    this.weight = 0,
    this.shared = 0,
    this.count = 0,
  });

  factory NodeRef.fromJson(Map<String, dynamic> j) => NodeRef(
        id: _str(j['id']),
        label: _str(j['label']),
        type: _str(j['type']).isEmpty ? 'concept' : _str(j['type']),
        group: _str(j['group']).isEmpty ? 'other' : _str(j['group']),
        passages: _int(j['passages']),
        weight: _dbl(j['weight']),
        shared: _int(j['shared']),
        count: _int(j['count']),
      );

  Color get color => kTypeColors[type] ?? groupColor(group);
}

class BookRef {
  final String id;
  final String title;
  final String author;
  final String categoryLabel;
  final int? year;
  final int count;

  const BookRef({required this.id, required this.title, this.author = '', this.categoryLabel = '', this.year, this.count = 0});

  factory BookRef.fromJson(Map<String, dynamic> j) => BookRef(
        id: _str(j['id']),
        title: _str(j['title']),
        author: _str(j['author']),
        categoryLabel: _str(j['category_label']),
        year: j['year'] == null ? null : _int(j['year']),
        count: _int(j['count']),
      );
}

class ChapterRef {
  final String docId;
  final String bookTitle;
  final int section;
  final String title;
  final String pages;
  final int count;

  const ChapterRef({
    required this.docId,
    required this.bookTitle,
    required this.section,
    required this.title,
    this.pages = '',
    this.count = 0,
  });

  factory ChapterRef.fromJson(Map<String, dynamic> j, {String? docId, String? bookTitle}) => ChapterRef(
        docId: _str(j['doc_id']).isEmpty ? (docId ?? '') : _str(j['doc_id']),
        bookTitle: _str(j['book_title']).isEmpty ? (bookTitle ?? '') : _str(j['book_title']),
        section: _int(j['section']),
        title: _str(j['title']),
        pages: _str(j['pages']),
        count: _int(j['count'] ?? j['passages']),
      );
}

class CPassage {
  final String docId;
  final String bookTitle;
  final int? section;
  final String? sectionTitle;
  final List<String> blockIds;
  final dynamic page;
  final String? pages;
  final String excerpt;

  const CPassage({
    required this.docId,
    required this.bookTitle,
    this.section,
    this.sectionTitle,
    this.blockIds = const [],
    this.page,
    this.pages,
    this.excerpt = '',
  });

  factory CPassage.fromJson(Map<String, dynamic> j) => CPassage(
        docId: _str(j['doc_id']),
        bookTitle: _str(j['book_title']),
        section: j['section'] == null ? null : _int(j['section']),
        sectionTitle: j['section_title']?.toString(),
        blockIds: (j['block_ids'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        page: j['page'],
        pages: j['pages']?.toString(),
        excerpt: _str(j['excerpt']),
      );

  String get where => [
        bookTitle,
        if (sectionTitle != null && sectionTitle!.isNotEmpty) sectionTitle!,
        if (pages != null && pages!.isNotEmpty) pages!,
      ].join(' · ');
}

class NodeDetail {
  final NodeRef node;
  final List<String> forms;
  final int peersTotal;
  final List<NodeRef> peers;
  final List<BookRef> books;
  final List<ChapterRef> chapters;
  final List<CPassage> passages;

  const NodeDetail({
    required this.node,
    this.forms = const [],
    required this.peersTotal,
    required this.peers,
    required this.books,
    required this.chapters,
    required this.passages,
  });

  factory NodeDetail.fromJson(Map<String, dynamic> j) {
    final node = j['node'] as Map<String, dynamic>? ?? const {};
    return NodeDetail(
      node: NodeRef.fromJson(node),
      forms: (node['forms'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
      peersTotal: _int(j['peers_total']),
      peers: [for (final p in _maps(j['peers'])) NodeRef.fromJson(p)],
      books: [for (final b in _maps(j['books'])) BookRef.fromJson(b)],
      chapters: [for (final c in _maps(j['chapters'])) ChapterRef.fromJson(c)],
      passages: [for (final p in _maps(j['passages'])) CPassage.fromJson(p)],
    );
  }
}

class MeetResult {
  final NodeRef a;
  final NodeRef b;
  final int total;
  final List<CPassage> passages;
  const MeetResult({required this.a, required this.b, required this.total, required this.passages});

  factory MeetResult.fromJson(Map<String, dynamic> j) => MeetResult(
        a: NodeRef.fromJson(j['a'] as Map<String, dynamic>? ?? const {}),
        b: NodeRef.fromJson(j['b'] as Map<String, dynamic>? ?? const {}),
        total: _int(j['total']),
        passages: [for (final p in _maps(j['passages'])) CPassage.fromJson(p)],
      );
}

class BookConcepts {
  final BookRef book;
  final List<NodeRef> concepts;
  final List<ChapterRef> chapters;
  const BookConcepts({required this.book, required this.concepts, required this.chapters});

  factory BookConcepts.fromJson(Map<String, dynamic> j) {
    final book = BookRef.fromJson(j['book'] as Map<String, dynamic>? ?? const {});
    return BookConcepts(
      book: book,
      concepts: [for (final c in _maps(j['concepts'])) NodeRef.fromJson(c)],
      chapters: [for (final c in _maps(j['chapters'])) ChapterRef.fromJson(c, docId: book.id, bookTitle: book.title)],
    );
  }
}

class ChapterConcepts {
  final BookRef book;
  final ChapterRef chapter;
  final List<NodeRef> concepts;
  final List<CPassage> passages;
  const ChapterConcepts({required this.book, required this.chapter, required this.concepts, required this.passages});

  factory ChapterConcepts.fromJson(Map<String, dynamic> j) {
    final book = BookRef.fromJson(j['book'] as Map<String, dynamic>? ?? const {});
    return ChapterConcepts(
      book: book,
      chapter: ChapterRef(
        docId: book.id,
        bookTitle: book.title,
        section: _int(j['section']),
        title: _str(j['title']),
        pages: _str(j['pages']),
      ),
      concepts: [for (final c in _maps(j['concepts'])) NodeRef.fromJson(c)],
      passages: [for (final p in _maps(j['passages'])) CPassage.fromJson(p)],
    );
  }
}

class ConceptSearch {
  final List<NodeRef> nodes;
  final List<BookRef> books;
  final List<ChapterRef> chapters;
  const ConceptSearch({this.nodes = const [], this.books = const [], this.chapters = const []});

  bool get isEmpty => nodes.isEmpty && books.isEmpty && chapters.isEmpty;

  factory ConceptSearch.fromJson(Map<String, dynamic> j) => ConceptSearch(
        nodes: [for (final n in _maps(j['nodes'])) NodeRef.fromJson(n)],
        books: [for (final b in _maps(j['books'])) BookRef.fromJson(b)],
        chapters: [for (final c in _maps(j['chapters'])) ChapterRef.fromJson(c)],
      );
}

/// Thrown while the server is still building the graph (HTTP 202).
class ConceptGraphBuilding implements Exception {
  final String message;
  final int pct;
  const ConceptGraphBuilding(this.message, this.pct);
}
