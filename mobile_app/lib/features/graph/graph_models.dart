/// Data models for the corpus knowledge graph (`/api/graph/*`).
library;

import 'package:flutter/material.dart';

/// Colour per taxonomy group. Chosen to read on both the light and the deep
/// navy dark surfaces.
const Map<String, Color> kGroupColors = {
  'steps': Color(0xFFF4A261), // gold
  'principles': Color(0xFF48B8D0), // cyan
  'struggles': Color(0xFFE76F51), // coral
  'practices': Color(0xFF4CAF50), // green
  'fellowship': Color(0xFF9B5DE5), // violet
  'relationships': Color(0xFFF15BB5), // pink
  'mind': Color(0xFF3A86FF), // blue
  'recovery': Color(0xFFFFD166), // yellow
};

Color groupColor(String group) => kGroupColors[group] ?? const Color(0xFF9DA7B3);

int _asInt(dynamic v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
double _asDouble(dynamic v) => v is num ? v.toDouble() : double.tryParse('$v') ?? 0.0;
String _asString(dynamic v) => v?.toString() ?? '';
List<Map<String, dynamic>> _asMaps(dynamic v) =>
    (v as List<dynamic>? ?? const []).whereType<Map<String, dynamic>>().toList();

class GraphGroup {
  final String id;
  final String label;
  const GraphGroup({required this.id, required this.label});
  factory GraphGroup.fromJson(Map<String, dynamic> j) =>
      GraphGroup(id: _asString(j['id']), label: _asString(j['label']));
}

class TopicNode {
  final String id;
  final String label;
  final String group;
  final String blurb;
  final int mentions;
  final int books;

  /// Relationship strength when returned as a neighbour (NPMI, 0..1).
  final double weight;
  final int shared;

  /// Passage count when returned in a book's topic profile.
  final int count;
  final double density;

  const TopicNode({
    required this.id,
    required this.label,
    required this.group,
    this.blurb = '',
    this.mentions = 0,
    this.books = 0,
    this.weight = 0,
    this.shared = 0,
    this.count = 0,
    this.density = 0,
  });

  factory TopicNode.fromJson(Map<String, dynamic> j) => TopicNode(
        id: _asString(j['id']),
        label: _asString(j['label']),
        group: _asString(j['group']),
        blurb: _asString(j['blurb']),
        mentions: _asInt(j['mentions']),
        books: _asInt(j['books']),
        weight: _asDouble(j['weight']),
        shared: _asInt(j['shared']),
        count: _asInt(j['count']),
        density: _asDouble(j['density']),
      );

  Color get color => groupColor(group);
}

/// A topic referenced from inside a passage ("also in this passage").
class TopicRef {
  final String id;
  final String label;
  final String group;
  final int hits;
  const TopicRef({required this.id, required this.label, required this.group, this.hits = 0});
  factory TopicRef.fromJson(Map<String, dynamic> j) => TopicRef(
        id: _asString(j['id']),
        label: _asString(j['label']),
        group: _asString(j['group']),
        hits: _asInt(j['hits']),
      );
  Color get color => groupColor(group);
}

class SectionRef {
  final int index;
  final String title;
  final int count;
  final dynamic printedPage;
  final String blockId;
  final int blocks;
  final List<TopicRef> topics;
  const SectionRef({
    required this.index,
    required this.title,
    this.count = 0,
    this.printedPage,
    this.blockId = '',
    this.blocks = 0,
    this.topics = const [],
  });
  factory SectionRef.fromJson(Map<String, dynamic> j) => SectionRef(
        index: _asInt(j['index']),
        title: _asString(j['title']),
        count: _asInt(j['count']),
        printedPage: j['printed_page'],
        blockId: _asString(j['block_id']),
        blocks: _asInt(j['blocks']),
        topics: _asMaps(j['topics']).map(TopicRef.fromJson).toList(),
      );
}

class BookNode {
  final String id;
  final String title;
  final String author;
  final String category;
  final String categoryLabel;
  final String? docId;
  final int passages;
  final int sectionCount;
  final List<String> topTopics;

  /// Present when the book is returned inside a topic.
  final int count;
  final double density;
  final List<SectionRef> sections;
  final List<Passage> topicPassages;

  const BookNode({
    required this.id,
    required this.title,
    this.author = '',
    this.category = '',
    this.categoryLabel = '',
    this.docId,
    this.passages = 0,
    this.sectionCount = 0,
    this.topTopics = const [],
    this.count = 0,
    this.density = 0,
    this.sections = const [],
    this.topicPassages = const [],
  });

  factory BookNode.fromJson(Map<String, dynamic> j) => BookNode(
        id: _asString(j['id']),
        title: _asString(j['title']),
        author: _asString(j['author']),
        category: _asString(j['category']),
        categoryLabel: _asString(j['category_label']),
        docId: j['doc_id']?.toString(),
        passages: _asInt(j['passages'] is List ? null : j['passages']),
        sectionCount: j['sections'] is List ? (j['sections'] as List).length : _asInt(j['sections']),
        topTopics: (j['top_topics'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        count: _asInt(j['count']),
        density: _asDouble(j['density']),
        sections: j['sections'] is List ? _asMaps(j['sections']).map(SectionRef.fromJson).toList() : const [],
        topicPassages: j['passages'] is List ? _asMaps(j['passages']).map(Passage.fromJson).toList() : const [],
      );

  String get byline => author.isEmpty ? categoryLabel : author;
}

class TopicEdge {
  final String source;
  final String target;
  final double weight;
  final int shared;
  const TopicEdge({required this.source, required this.target, required this.weight, required this.shared});
  factory TopicEdge.fromJson(Map<String, dynamic> j) => TopicEdge(
        source: _asString(j['source']),
        target: _asString(j['target']),
        weight: _asDouble(j['weight']),
        shared: _asInt(j['shared']),
      );
}

class BookEdge {
  final String topic;
  final String book;
  final int count;
  final double density;
  const BookEdge({required this.topic, required this.book, required this.count, required this.density});
  factory BookEdge.fromJson(Map<String, dynamic> j) => BookEdge(
        topic: _asString(j['topic']),
        book: _asString(j['book']),
        count: _asInt(j['count']),
        density: _asDouble(j['density']),
      );
}

class GraphMap {
  final List<GraphGroup> groups;
  final List<TopicNode> topics;
  final List<BookNode> books;
  final List<TopicEdge> topicEdges;
  final List<BookEdge> bookEdges;
  final int passageCount;

  const GraphMap({
    required this.groups,
    required this.topics,
    required this.books,
    required this.topicEdges,
    required this.bookEdges,
    required this.passageCount,
  });

  factory GraphMap.fromJson(Map<String, dynamic> j) => GraphMap(
        groups: _asMaps(j['groups']).map(GraphGroup.fromJson).toList(),
        topics: _asMaps(j['topics']).map(TopicNode.fromJson).toList(),
        books: _asMaps(j['books']).map(BookNode.fromJson).toList(),
        topicEdges: _asMaps(j['topic_edges']).map(TopicEdge.fromJson).toList(),
        bookEdges: _asMaps(j['book_edges']).map(BookEdge.fromJson).toList(),
        passageCount: _asInt((j['stats'] as Map<String, dynamic>? ?? const {})['passages']),
      );

  TopicNode? topic(String id) {
    for (final t in topics) {
      if (t.id == id) return t;
    }
    return null;
  }

  BookNode? book(String id) {
    for (final b in books) {
      if (b.id == id) return b;
    }
    return null;
  }
}

class Passage {
  final String chunkId;
  final String bookId;
  final String bookTitle;
  final String? docId;
  final List<String> blockIds;
  final String? section;
  final int? sectionIndex;
  final dynamic printedPage;
  final int words;
  final int hits;
  final String excerpt;
  final List<TopicRef> topics;
  final double? similarity;

  const Passage({
    required this.chunkId,
    required this.bookId,
    required this.bookTitle,
    this.docId,
    this.blockIds = const [],
    this.section,
    this.sectionIndex,
    this.printedPage,
    this.words = 0,
    this.hits = 0,
    this.excerpt = '',
    this.topics = const [],
    this.similarity,
  });

  factory Passage.fromJson(Map<String, dynamic> j) => Passage(
        chunkId: _asString(j['chunk_id']),
        bookId: _asString(j['book_id']),
        bookTitle: _asString(j['book_title']),
        docId: j['doc_id']?.toString(),
        blockIds: (j['block_ids'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        section: j['section']?.toString(),
        sectionIndex: j['section_index'] == null ? null : _asInt(j['section_index']),
        printedPage: j['printed_page'],
        words: _asInt(j['words']),
        hits: _asInt(j['hits']),
        excerpt: _asString(j['excerpt']),
        topics: _asMaps(j['topics']).map(TopicRef.fromJson).toList(),
        similarity: j['similarity'] == null ? null : _asDouble(j['similarity']),
      );

  /// "How It Works · p. 64" style locator.
  String get locator {
    final parts = <String>[];
    if (section != null && section!.isNotEmpty) parts.add(section!);
    if (printedPage != null && '$printedPage'.isNotEmpty) parts.add('p. $printedPage');
    return parts.join(' · ');
  }
}

class TopicDetail {
  final TopicNode topic;
  final List<TopicNode> related;
  final List<BookNode> books;
  final int totalBooks;
  const TopicDetail({required this.topic, required this.related, required this.books, required this.totalBooks});
  factory TopicDetail.fromJson(Map<String, dynamic> j) => TopicDetail(
        topic: TopicNode.fromJson(j['topic'] as Map<String, dynamic>),
        related: _asMaps(j['related']).map(TopicNode.fromJson).toList(),
        books: _asMaps(j['books']).map(BookNode.fromJson).toList(),
        totalBooks: _asInt(j['total_books']),
      );
}

class BookDetail {
  final BookNode book;
  final List<TopicNode> topics;
  final List<SectionRef> sections;
  const BookDetail({required this.book, required this.topics, required this.sections});
  factory BookDetail.fromJson(Map<String, dynamic> j) => BookDetail(
        book: BookNode.fromJson(j['book'] as Map<String, dynamic>),
        topics: _asMaps(j['topics']).map(TopicNode.fromJson).toList(),
        sections: _asMaps(j['sections']).map(SectionRef.fromJson).toList(),
      );
}

class PassagePage {
  final TopicNode topic;
  final BookNode? book;
  final String sort;
  final int offset;
  final int total;
  final List<Passage> passages;
  const PassagePage({
    required this.topic,
    required this.book,
    required this.sort,
    required this.offset,
    required this.total,
    required this.passages,
  });
  factory PassagePage.fromJson(Map<String, dynamic> j) => PassagePage(
        topic: TopicNode.fromJson(j['topic'] as Map<String, dynamic>),
        book: j['book'] == null ? null : BookNode.fromJson(j['book'] as Map<String, dynamic>),
        sort: _asString(j['sort']),
        offset: _asInt(j['offset']),
        total: _asInt(j['total']),
        passages: _asMaps(j['passages']).map(Passage.fromJson).toList(),
      );
}

class GraphSearchResult {
  final String query;
  final List<TopicNode> topics;
  final List<TopicNode> suggestedTopics;
  final List<Passage> passages;
  const GraphSearchResult({
    required this.query,
    required this.topics,
    required this.suggestedTopics,
    required this.passages,
  });
  factory GraphSearchResult.fromJson(Map<String, dynamic> j) => GraphSearchResult(
        query: _asString(j['query']),
        topics: _asMaps(j['topics']).map(TopicNode.fromJson).toList(),
        suggestedTopics: _asMaps(j['suggested_topics']).map(TopicNode.fromJson).toList(),
        passages: _asMaps(j['passages']).map(Passage.fromJson).toList(),
      );
}

class WindowBlock {
  final String id;
  final String type;
  final String text;
  final dynamic printedPage;
  final bool highlight;
  const WindowBlock({
    required this.id,
    required this.type,
    required this.text,
    this.printedPage,
    this.highlight = false,
  });
  factory WindowBlock.fromJson(Map<String, dynamic> j) => WindowBlock(
        id: _asString(j['id']),
        type: _asString(j['type']),
        text: _asString(j['text']),
        printedPage: j['printed_page'],
        highlight: j['highlight'] == true,
      );
}

class DocWindow {
  final String docId;
  final String title;
  final String author;
  final bool found;
  final String? heading;
  final int start;
  final int end;
  final int total;
  final String? prevBlock;
  final String? nextBlock;
  final List<WindowBlock> blocks;
  const DocWindow({
    required this.docId,
    required this.title,
    required this.author,
    this.found = true,
    this.heading,
    required this.start,
    required this.end,
    required this.total,
    this.prevBlock,
    this.nextBlock,
    required this.blocks,
  });
  factory DocWindow.fromJson(Map<String, dynamic> j) => DocWindow(
        docId: _asString(j['doc_id']),
        title: _asString(j['title']),
        author: _asString(j['author']),
        found: j['found'] != false,
        heading: j['heading']?.toString(),
        start: _asInt(j['start']),
        end: _asInt(j['end']),
        total: _asInt(j['total']),
        prevBlock: j['prev_block']?.toString(),
        nextBlock: j['next_block']?.toString(),
        blocks: _asMaps(j['blocks']).map(WindowBlock.fromJson).toList(),
      );
}

/// Server is still building the graph (HTTP 202).
class GraphBuilding implements Exception {
  final String status;
  final int progress;
  const GraphBuilding(this.status, this.progress);
  @override
  String toString() => 'GraphBuilding($status, $progress%)';
}
