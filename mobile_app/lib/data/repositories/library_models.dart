class OfflineBookIndex {
  final String docId;
  final String title;
  final String author;
  final String category;
  final int blocksCount;

  OfflineBookIndex({
    required this.docId,
    required this.title,
    required this.author,
    required this.category,
    required this.blocksCount,
  });

  factory OfflineBookIndex.fromJson(Map<String, dynamic> json) {
    return OfflineBookIndex(
      docId: (json['doc_id'] ?? '').toString(),
      title: (json['title'] ?? '').toString(),
      author: (json['author'] ?? '').toString(),
      category: (json['category'] ?? '').toString(),
      blocksCount: json['blocks_count'] is int ? json['blocks_count'] as int : 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'doc_id': docId,
        'title': title,
        'author': author,
        'category': category,
        'blocks_count': blocksCount,
      };
}

class OfflineSearchResult {
  final String docId;
  final String blockId;
  final String heading;
  final String text;

  OfflineSearchResult({
    required this.docId,
    required this.blockId,
    required this.heading,
    required this.text,
  });
}
