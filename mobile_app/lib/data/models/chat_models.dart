import 'dart:math';

/// A retrieved source / citation. Mirrors a /api/chat "sources[]" object.
class Source {
  final String source; // e.g. "as_bill_sees_it.pdf" (raw filename/source id)
  final double similarity; // 0..1 (rounded to 3 by server)
  final String url; // e.g. "/api/documents/aa/Big_Book.pdf"
  final String excerpt;
  final String? matchScale; // server "match_scale" (nullable)
  final String? contextScale; // server "context_scale" (nullable)
  final String? docId;
  final List<String>? blockIds;
  final dynamic page; // printed page number (printed_page_start)

  const Source({
    required this.source,
    required this.similarity,
    required this.url,
    required this.excerpt,
    this.matchScale,
    this.contextScale,
    this.docId,
    this.blockIds,
    this.page,
  });

  factory Source.fromJson(Map<String, dynamic> json) {
    return Source(
      source: (json['source'] ?? '').toString(),
      similarity: _asDouble(json['similarity']),
      url: (json['url'] ?? '').toString(),
      excerpt: (json['excerpt'] ?? '').toString(),
      matchScale: json['match_scale']?.toString(),
      contextScale: json['context_scale']?.toString(),
      docId: json['doc_id']?.toString(),
      blockIds: json['block_ids'] != null
          ? (json['block_ids'] as List<dynamic>).map((e) => e.toString()).toList()
          : null,
      page: json['page'],
    );
  }

  Map<String, dynamic> toJson() => {
        'source': source,
        'similarity': similarity,
        'url': url,
        'excerpt': excerpt,
        if (matchScale != null) 'match_scale': matchScale,
        if (contextScale != null) 'context_scale': contextScale,
        if (docId != null) 'doc_id': docId,
        if (blockIds != null) 'block_ids': blockIds,
        if (page != null) 'page': page,
      };

  /// Human title derived from the filename: basename, strip ext, '_'->' ',
  /// keep text before " - " if present.
  String get title {
    var base = source;
    // basename: drop any path component
    final slash = base.lastIndexOf('/');
    if (slash >= 0) base = base.substring(slash + 1);
    final backslash = base.lastIndexOf('\\');
    if (backslash >= 0) base = base.substring(backslash + 1);
    // strip extension
    final dot = base.lastIndexOf('.');
    if (dot > 0) base = base.substring(0, dot);
    // underscores -> spaces
    base = base.replaceAll('_', ' ');
    // keep text before " - " if present
    final dashIdx = base.indexOf(' - ');
    if (dashIdx >= 0) base = base.substring(0, dashIdx);
    return base.trim();
  }

  /// Absolute render URL given a baseUrl: prefers "/api/doc/<doc_id>" when docId
  /// is present, otherwise falls back to "/api/render/..." with highlight query.
  String renderUrl(String baseUrl, {String? highlight}) {
    final base = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    if (docId != null && docId!.isNotEmpty) {
      final blocksParam = blockIds != null && blockIds!.isNotEmpty
          ? '?blocks=${Uri.encodeQueryComponent(blockIds!.join(','))}'
          : '';
      return '$base/api/doc/$docId$blocksParam';
    }
    var path = url.replaceFirst('/api/documents/', '/api/render/');
    if (!path.startsWith('/')) path = '/$path';
    var full = '$base$path';
    if (highlight != null && highlight.isNotEmpty) {
      final sep = full.contains('?') ? '&' : '?';
      full = '$full${sep}highlight=${Uri.encodeQueryComponent(highlight)}';
    }
    return full;
  }

  /// Stable key for de-duping a list of sources by document.
  String get documentKey => url.isNotEmpty ? url : source;
}

/// One chat turn. role is 'user' or 'assistant'.
class ChatMessage {
  final String id; // local uuid
  final String role; // 'user' | 'assistant'
  final String text; // markdown body (answer or user text)
  final List<Source> sources; // assistant only
  final List<String> followups; // assistant only ("Keep exploring")
  final String thinking; // accumulated reasoning (assistant only)
  final bool isStreaming; // true while tokens are arriving
  final bool isError; // true if this message represents an error
  final String? query; // the user prompt this answer responds to
  final String? highlightSeed; // text used to deep-link sources (query[+hyde])
  final DateTime createdAt;
  final bool isDenoising; // true while the diffusion engine is denoising
  final int? diffusionStep; // current step of denoising
  final int? diffusionTotal; // total steps of denoising
  final String? diffusionContent; // transient visual snapshot text
  final List<String> imageThumbs; // user-attached photo data URLs (for display)

  const ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    this.sources = const [],
    this.followups = const [],
    this.thinking = '',
    this.isStreaming = false,
    this.isError = false,
    this.query,
    this.highlightSeed,
    required this.createdAt,
    this.isDenoising = false,
    this.diffusionStep,
    this.diffusionTotal,
    this.diffusionContent,
    this.imageThumbs = const [],
  });

  factory ChatMessage.user(String text, {List<String> images = const []}) =>
      ChatMessage(
        id: _genId(),
        role: 'user',
        text: text,
        createdAt: DateTime.now(),
        imageThumbs: images,
      );

  factory ChatMessage.assistantPlaceholder({String? query}) => ChatMessage(
        id: _genId(),
        role: 'assistant',
        text: '',
        isStreaming: true,
        query: query,
        createdAt: DateTime.now(),
        isDenoising: false,
      );

  ChatMessage copyWith({
    String? text,
    List<Source>? sources,
    List<String>? followups,
    String? thinking,
    bool? isStreaming,
    bool? isError,
    String? query,
    String? highlightSeed,
    bool? isDenoising,
    int? diffusionStep,
    int? diffusionTotal,
    String? diffusionContent,
    List<String>? imageThumbs,
  }) {
    return ChatMessage(
      id: id,
      role: role,
      text: text ?? this.text,
      sources: sources ?? this.sources,
      followups: followups ?? this.followups,
      thinking: thinking ?? this.thinking,
      isStreaming: isStreaming ?? this.isStreaming,
      isError: isError ?? this.isError,
      query: query ?? this.query,
      highlightSeed: highlightSeed ?? this.highlightSeed,
      createdAt: createdAt,
      isDenoising: isDenoising ?? this.isDenoising,
      diffusionStep: diffusionStep ?? this.diffusionStep,
      diffusionTotal: diffusionTotal ?? this.diffusionTotal,
      diffusionContent: diffusionContent ?? this.diffusionContent,
      imageThumbs: imageThumbs ?? this.imageThumbs,
    );
  }

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    return ChatMessage(
      id: (json['id'] ?? _genId()).toString(),
      role: (json['role'] ?? 'assistant').toString(),
      text: (json['text'] ?? '').toString(),
      sources: (json['sources'] as List<dynamic>? ?? const [])
          .map((e) => Source.fromJson(e as Map<String, dynamic>))
          .toList(),
      followups: (json['followups'] as List<dynamic>? ?? const [])
          .map((e) => e.toString())
          .toList(),
      thinking: (json['thinking'] ?? '').toString(),
      isStreaming: json['isStreaming'] == true,
      isError: json['isError'] == true,
      query: json['query']?.toString(),
      highlightSeed: json['highlightSeed']?.toString(),
      createdAt: DateTime.tryParse((json['createdAt'] ?? '').toString()) ??
          DateTime.now(),
      isDenoising: json['isDenoising'] == true,
      diffusionStep: json['diffusionStep'] as int?,
      diffusionTotal: json['diffusionTotal'] as int?,
      diffusionContent: json['diffusionContent']?.toString(),
      imageThumbs: (json['imageThumbs'] as List<dynamic>? ?? const [])
          .map((e) => e.toString())
          .toList(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'role': role,
        'text': text,
        'sources': sources.map((e) => e.toJson()).toList(),
        'followups': followups,
        'thinking': thinking,
        'isStreaming': isStreaming,
        'isError': isError,
        if (query != null) 'query': query,
        if (highlightSeed != null) 'highlightSeed': highlightSeed,
        'createdAt': createdAt.toIso8601String(),
        'isDenoising': isDenoising,
        if (diffusionStep != null) 'diffusionStep': diffusionStep,
        if (diffusionTotal != null) 'diffusionTotal': diffusionTotal,
        if (diffusionContent != null) 'diffusionContent': diffusionContent,
        if (imageThumbs.isNotEmpty) 'imageThumbs': imageThumbs,
      };

  /// {"role": role, "content": text} for the /api/chat history array.
  Map<String, String> toHistoryJson() => {'role': role, 'content': text};

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';
}

/// A saved/persisted conversation.
class Conversation {
  final String id; // uuid
  final String title; // first user message, truncated
  final List<ChatMessage> messages;
  final DateTime createdAt;
  final DateTime updatedAt;

  const Conversation({
    required this.id,
    required this.title,
    required this.messages,
    required this.createdAt,
    required this.updatedAt,
  });

  factory Conversation.create() {
    final now = DateTime.now();
    return Conversation(
      id: _genId(),
      title: 'New conversation',
      messages: const [],
      createdAt: now,
      updatedAt: now,
    );
  }

  Conversation copyWith({
    String? title,
    List<ChatMessage>? messages,
    DateTime? updatedAt,
  }) {
    return Conversation(
      id: id,
      title: title ?? this.title,
      messages: messages ?? this.messages,
      createdAt: createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }

  factory Conversation.fromJson(Map<String, dynamic> json) {
    final now = DateTime.now();
    return Conversation(
      id: (json['id'] ?? _genId()).toString(),
      title: (json['title'] ?? 'New conversation').toString(),
      messages: (json['messages'] as List<dynamic>? ?? const [])
          .map((e) => ChatMessage.fromJson(e as Map<String, dynamic>))
          .toList(),
      createdAt:
          DateTime.tryParse((json['createdAt'] ?? '').toString()) ?? now,
      updatedAt:
          DateTime.tryParse((json['updatedAt'] ?? '').toString()) ?? now,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'messages': messages.map((e) => e.toJson()).toList(),
        'createdAt': createdAt.toIso8601String(),
        'updatedAt': updatedAt.toIso8601String(),
      };

  /// Derives a title from the first user message (max ~48 chars).
  static String deriveTitle(List<ChatMessage> messages) {
    final firstUser = messages.where((m) => m.isUser).cast<ChatMessage?>().firstWhere(
          (m) => (m?.text.trim().isNotEmpty ?? false),
          orElse: () => null,
        );
    final raw = firstUser?.text.trim() ?? '';
    if (raw.isEmpty) return 'New conversation';
    final oneLine = raw.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (oneLine.length <= 48) return oneLine;
    return '${oneLine.substring(0, 47).trimRight()}…';
  }
}

/// /api/suggest item: {"text": "...", "source": "..."}.
class Suggestion {
  final String text;
  final String source;
  const Suggestion({required this.text, required this.source});

  factory Suggestion.fromJson(dynamic json) {
    if (json is String) {
      return Suggestion(text: json, source: '');
    }
    if (json is Map<String, dynamic>) {
      return Suggestion(
        text: (json['text'] ?? '').toString(),
        source: (json['source'] ?? '').toString(),
      );
    }
    return Suggestion(text: json.toString(), source: '');
  }
}

// ---------------------------------------------------------------------------
// ChatEvent (typed SSE event)
// ---------------------------------------------------------------------------

/// One decoded "data: {json}" line from the /api/chat stream.
sealed class ChatEvent {
  const ChatEvent();

  /// Parse a single decoded JSON object into the right subtype.
  /// Returns null for keepalive/unrecognized payloads.
  static ChatEvent? fromJson(Map<String, dynamic> json) {
    if (json.containsKey('error')) {
      return ErrorEvent((json['error'] ?? '').toString());
    }
    if (json['done'] == true) {
      return const DoneEvent();
    }
    if (json.containsKey('sources')) {
      final list = (json['sources'] as List<dynamic>? ?? const [])
          .map((e) => Source.fromJson(e as Map<String, dynamic>))
          .toList();
      return SourcesEvent(
        list,
        expandedQuery: json['expanded_query']?.toString(),
      );
    }
    if (json.containsKey('thinking')) {
      return ThinkingEvent((json['thinking'] ?? '').toString());
    }
    if (json.containsKey('token')) {
      return TokenEvent((json['token'] ?? '').toString());
    }
    if (json.containsKey('followups')) {
      final items = (json['followups'] as List<dynamic>? ?? const [])
          .map((e) => e.toString())
          .toList();
      return FollowupsEvent(items);
    }
    if (json.containsKey('diffusion')) {
      final diff = json['diffusion'] as Map<String, dynamic>? ?? const {};
      return DiffusionEvent(
        block: _asInt(diff['block']),
        step: _asInt(diff['step']),
        total: _asInt(diff['total']),
        content: (diff['content'] ?? '').toString(),
      );
    }
    return null;
  }
}

class SourcesEvent extends ChatEvent {
  // first event
  final List<Source> sources;
  final String? expandedQuery; // "expanded_query" (HyDE)
  const SourcesEvent(this.sources, {this.expandedQuery});
}

class ThinkingEvent extends ChatEvent {
  // only when showThinking
  final String text;
  const ThinkingEvent(this.text);
}

class TokenEvent extends ChatEvent {
  // append to answer
  final String text;
  const TokenEvent(this.text);
}

class FollowupsEvent extends ChatEvent {
  // near end
  final List<String> items;
  const FollowupsEvent(this.items);
}

class DiffusionEvent extends ChatEvent {
  final int block;
  final int step;
  final int total;
  final String content;

  const DiffusionEvent({
    required this.block,
    required this.step,
    required this.total,
    required this.content,
  });
}

class ErrorEvent extends ChatEvent {
  final String message;
  const ErrorEvent(this.message);
}

class DoneEvent extends ChatEvent {
  // terminal {"done": true}
  const DoneEvent();
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

double _asDouble(dynamic v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v) ?? 0.0;
  return 0.0;
}

int _asInt(dynamic v) {
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? 0;
  return 0;
}

final Random _rng = Random();

/// Lightweight uuid-ish local id (no external dependency).
String _genId() {
  final ts = DateTime.now().microsecondsSinceEpoch.toRadixString(16);
  final rand = _rng.nextInt(0x7fffffff).toRadixString(16);
  return '$ts-$rand';
}
