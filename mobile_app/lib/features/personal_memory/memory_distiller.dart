// FR11 Task 2 — MemoryDistiller: one-shot fact/thread extraction at
// conversation END.
//
// Takes the last 12 turns of a finished conversation and asks an LLM (via an
// injected [DistillTransport]) to return strict JSON: durable new facts +
// open threads worth resuming. Everything here is offline-testable — tests
// swap in a fake transport; no network is ever touched in tests.
//
// Privacy contract (FR11 hard rule #1): distillation sends only THAT
// conversation's last-12-turn tail, never other conversations and never
// stored memory bodies. In server mode the tail goes to the PRODUCT server's
// /api/distill passthrough, which builds the prompt with this same
// instruction text, forwards ONLY the prompt to the shared local inference
// engine, and stores nothing — the transcript exists solely within that one
// request (mirrors /api/chat's non-persistence default). In Private Mode the
// [LocalDistillTransport] never leaves the device.

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/distill_generator.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

// ---------------------------------------------------------------------------
// Limits (shared with the prompt so the model and the parser agree).
// ---------------------------------------------------------------------------

/// How many most-recent transcript turns are shown to the model.
const int kDistillWindowTurns = 12;

/// Maximum durable facts extracted per conversation.
const int kDistillMaxFacts = 3;

/// Maximum open threads extracted per conversation.
const int kDistillMaxThreads = 2;

/// Hard cap on a single fact's length (guardrail: no verbatim message bodies,
/// no rambling).
const int kDistillMaxFactChars = 120;

/// Hard cap on a thread title.
const int kDistillMaxTitleChars = 50;

/// Hard cap on a thread's detail/next-step note.
const int kDistillMaxDetailChars = 120;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Raised by any distillation failure: transport errors AND malformed JSON
/// from the model. ChatNotifier catches this and silently skips distillation
/// — it must never block or surface in the chat UX.
class MemoryDistillError implements Exception {
  final String message;
  const MemoryDistillError(this.message);

  @override
  String toString() => 'MemoryDistillError: $message';
}

// ---------------------------------------------------------------------------
// Transport abstraction
// ---------------------------------------------------------------------------

/// One-shot LLM completion. Implementations must be injectable so tests run
/// fully offline with a fake transport.
abstract class DistillTransport {
  /// Sends [prompt] and returns the model's raw completion text.
  /// Implementations may throw [MemoryDistillError].
  Future<String> complete(String prompt);

  /// Picks the transport for the app's CURRENT backend (FR11 Wave B).
  ///
  /// Private Mode with a usable on-device generator -> [LocalDistillTransport]
  /// (purely on-device). Anything else -> [ServerDistillTransport] pointed at
  /// the PRODUCT server's `/api/distill` passthrough, which forwards only the
  /// built prompt to the shared inference engine and stores nothing — the
  /// product path is what the app uses in server mode.
  factory DistillTransport.forBackend({
    required bool privateMode,
    required String serverBaseUrl,
    http.Client? client,
    Future<String> Function(String)? localGenerator,
  }) {
    if (privateMode && localGenerator != null) {
      return LocalDistillTransport(generator: localGenerator);
    }
    return ServerDistillTransport(baseUrl: serverBaseUrl, client: client);
  }
}

/// Server-mode transport (FR11 Wave B product passthrough).
///
/// [completeProduct] POSTs the transcript tail + existing-memory digest to
/// `{baseUrl}/api/distill` — the product server builds the prompt with the
/// SAME instruction text this module uses, forwards it to the shared
/// inference engine, and returns parsed `{new_facts, threads}`. The
/// transcript exists only inside that single request; the server stores
/// nothing (mirrors /api/chat's non-persistence default).
///
/// There is deliberately NO direct-to-inference-host path here: a phone on
/// the public internet cannot reach the LAN inference host, and routing raw
/// transcript prompts through the product `/api/chat` would widen the
/// server-visible surface beyond the one chat already uses.
class ServerDistillTransport implements DistillTransport {
  final String baseUrl;
  final http.Client _client;

  ServerDistillTransport({required this.baseUrl, http.Client? client})
      : _client = client ?? http.Client();

  @override
  Future<String> complete(String prompt) async {
    // The abstract API is prompt-shaped (LocalDistillTransport needs that),
    // but the server path must carry the STRUCTURED transcript so the server
    // can window/clamp it; handing this transport a built prompt would only
    // be usable by a legacy direct-to-inference route that no longer exists.
    throw MemoryDistillError(
      'ServerDistillTransport requires completeProduct(); use '
      'MemoryDistiller.distill() which routes server transports through it.',
    );
  }

  /// Product passthrough path (FR11 Wave B): POSTs [transcript] (already the
  /// last-[kDistillWindowTurns] window, error turns filtered) plus the
  /// existing-memory digest to `{baseUrl}/api/distill` and returns the
  /// response body verbatim — a JSON string of `{new_facts, threads}` that
  /// the shared [MemoryDistiller] parser re-parses (and re-caps) unchanged.
  ///
  /// Non-200 and unparseable responses throw [MemoryDistillError], keeping
  /// the failure semantics identical to the legacy path.
  Future<String> completeProduct({
    required List<ChatMessage> transcript,
    Map<String, dynamic>? existingMemoryDigest,
  }) async {
    final normalized = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    final uri = Uri.parse('$normalized/api/distill');
    final turns = <Map<String, String>>[
      for (final m in transcript)
        if (!m.isError && m.text.trim().isNotEmpty)
          {
            'role': m.isUser ? 'user' : 'assistant',
            'content': _cap(m.text.trim(), 2000),
          },
    ];
    final body = <String, dynamic>{
      'transcript': turns,
      if (existingMemoryDigest != null) 'existing': existingMemoryDigest,
    };
    try {
      final res = await _client.post(
        uri,
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
      if (res.statusCode != 200) {
        throw MemoryDistillError('server transport failed');
      }
      // Body is {new_facts, threads} JSON; the shared MemoryDistiller parser
      // validates shape + applies the caps. An unparseable body surfaces as
      // MemoryDistillError there — the caller swallows it silently.
      return res.body;
    } on MemoryDistillError {
      rethrow;
    } catch (_) {
      // Network errors, timeouts, HTTP/JSON parse failures — all one error.
      throw MemoryDistillError('server transport failed');
    }
  }
}

/// Private-Mode transport: delegates to an injected one-shot generator
/// (Task 3 wires flutter_gemma through this callback). Purely on-device;
/// when no generator is wired it fails fast with [MemoryDistillError].
class LocalDistillTransport implements DistillTransport {
  final Future<String> Function(String prompt)? generator;

  LocalDistillTransport({this.generator});

  @override
  Future<String> complete(String prompt) async {
    final gen = generator;
    if (gen == null) {
      throw MemoryDistillError('local transport unavailable');
    }
    return gen(prompt);
  }
}

// ---------------------------------------------------------------------------
// DTOs (local to this file; Task 3 maps DistilledThread onto the
// personal_memory.dart MemoryThread).
// ---------------------------------------------------------------------------

/// One open thread worth resuming in a later conversation.
class DistilledThread {
  final String id; // kebab-case slug, e.g. 'step-8-amends'
  final String title; // <= 50 chars
  final String detail; // <= 120 chars: last known state / next step
  final bool resolved;

  const DistilledThread({
    required this.id,
    required this.title,
    this.detail = '',
    this.resolved = false,
  });
}

/// The outcome of one distillation run: brand-new durable facts (already
/// deduped against the existing-memory digest the prompt was given) and open
/// threads.
class DistillResult {
  final List<String> newFacts;
  final List<DistilledThread> threads;

  const DistillResult({required this.newFacts, required this.threads});

  bool get isEmpty => newFacts.isEmpty && threads.isEmpty;
}

// ---------------------------------------------------------------------------
// Prompt
// ---------------------------------------------------------------------------

/// Instructions shown to the model on every distillation. Strict JSON only.
const String kMemoryDistillPrompt = '''
You are reading the last $kDistillWindowTurns turns of a finished recovery-support chat
between a person and their sober-companion assistant. Extract only what is
worth the assistant remembering in FUTURE conversations. Keep the person's
dignity; never use judgment phrasing about them or their recovery.

Reply with STRICT JSON only — no markdown fences, no prose, no commentary —
matching EXACTLY this schema:
{"new_facts": ["..."], "threads": [{"id": "kebab-case-slug", "title": "...", "detail": "...", "resolved": false}]}

Rules:
- new_facts: up to $kDistillMaxFacts durable traits, preferences, or plans about the
  person that would matter later, written in the THIRD person (e.g. "Prefers
  evening meetings over morning ones"). Max $kDistillMaxFactChars chars each.
  NEVER copy message bodies verbatim. No medical or diagnostic claims.
- threads: up to $kDistillMaxThreads UNFINISHED topics from this conversation worth
  resuming. "id" is a kebab-case slug; "title" max $kDistillMaxTitleChars chars;
  "detail" max $kDistillMaxDetailChars chars (where it left off / natural next
  step). "resolved" is always false.
- If nothing is worth remembering, return empty arrays.

Existing memory is listed below ONLY to prevent duplicates — never re-issue a
fact or thread already recorded there.
''';

// ---------------------------------------------------------------------------
// MemoryDistiller
// ---------------------------------------------------------------------------

/// Runs one [DistillTransport] completion over the tail of a conversation and
/// parses the result. Never retries: a malformed model response throws
/// [MemoryDistillError] and the caller decides how to degrade.
class MemoryDistiller {
  final DistillTransport transport;

  MemoryDistiller({required this.transport});

  /// Extracts facts/threads from the last [kDistillWindowTurns] turns of
  /// [transcript]. [existingMemoryDigest] is an optional map of already-known
  /// titles — `{'facts': [...], 'threads': [...]}` — folded into the prompt so
  /// the model dedupes against them. Error turns (and their content) never
  /// enter the prompt.
  ///
  /// Routing: when [transport] is a [ServerDistillTransport], the transcript +
  /// digest go through its product passthrough path ([ServerDistillTransport.completeProduct]
  /// -> the product server's `/api/distill`, which builds the prompt with the
  /// same instruction text and forwards only it to the shared inference
  /// engine). Any other transport gets the locally-built prompt via
  /// [DistillTransport.complete].
  ///
  /// Throws [MemoryDistillError] if the transport fails or the response is
  /// malformed JSON.
  Future<DistillResult> distill(
    List<ChatMessage> transcript, {
    Map<String, dynamic>? existingMemoryDigest,
  }) async {
    final turns = transcript.where((m) => !m.isError).toList();
    final window = turns.length <= kDistillWindowTurns
        ? turns
        : turns.sublist(turns.length - kDistillWindowTurns);

    final t = transport;
    final String raw;
    if (t is ServerDistillTransport) {
      raw = await t.completeProduct(
        transcript: window,
        existingMemoryDigest: existingMemoryDigest,
      );
    } else {
      raw = await t.complete(_buildPrompt(window, existingMemoryDigest));
    }
    return _parseResult(raw);
  }

  String _buildPrompt(
    List<ChatMessage> window,
    Map<String, dynamic>? existingMemoryDigest,
  ) {
    final buf = StringBuffer(kMemoryDistillPrompt);

    final knownFacts = _digestTitles(existingMemoryDigest, 'facts');
    final knownThreads = _digestTitles(existingMemoryDigest, 'threads');
    buf.writeln();
    buf.writeln('Existing memory — facts: $knownFacts');
    buf.writeln('Existing memory — open threads: $knownThreads');
    buf.writeln();

    buf.writeln('Conversation (last ${window.length} turns):');
    for (final m in window) {
      final role = m.isUser ? 'User' : 'Assistant';
      buf.writeln('$role: ${m.text.trim()}');
    }
    return buf.toString();
  }

  static String _digestTitles(Map<String, dynamic>? digest, String key) {
    if (digest == null) return '(none)';
    final value = digest[key];
    if (value is! List || value.isEmpty) return '(none)';
    final titles = value
        .whereType<String>()
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    if (titles.isEmpty) return '(none)';
    return '[${titles.join(' | ')}]';
  }
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

DistillResult _parseResult(String raw) {
  final map = _decodeJsonObject(raw);
  if (map == null) {
    throw MemoryDistillError('malformed JSON from distillation');
  }

  final facts = <String>[];
  final rawFacts = map['new_facts'];
  if (rawFacts is List) {
    for (final item in rawFacts) {
      if (facts.length >= kDistillMaxFacts) break;
      if (item is! String) continue; // drop non-string garbage
      final t = item.trim();
      if (t.isEmpty) continue;
      facts.add(_cap(t, kDistillMaxFactChars));
    }
  }

  final threads = <DistilledThread>[];
  final rawThreads = map['threads'];
  if (rawThreads is List) {
    for (final item in rawThreads) {
      if (threads.length >= kDistillMaxThreads) break;
      if (item is! Map) continue; // drop non-map garbage
      final id = (item['id'] ?? '').toString().trim();
      final title = _cap((item['title'] ?? '').toString().trim(),
          kDistillMaxTitleChars);
      final detail = _cap((item['detail'] ?? '').toString().trim(),
          kDistillMaxDetailChars);
      final resolved = item['resolved'] == true;
      if (id.isEmpty && title.isEmpty) continue; // nothing usable
      threads.add(DistilledThread(
        id: id.isEmpty ? _slugify(title) : id,
        title: title,
        detail: detail,
        resolved: resolved,
      ));
    }
  }

  return DistillResult(newFacts: facts, threads: threads);
}

/// Decodes a model completion into a JSON object. Tolerates markdown fences
/// and prose wrapped around the JSON (falls back to the first `{...}` block).
/// Returns null when no valid JSON object can be found.
Map<String, dynamic>? _decodeJsonObject(String raw) {
  var text = raw.trim();

  // Strip ```json ... ``` fences (with or without a language tag).
  if (text.startsWith('```')) {
    final firstNl = text.indexOf('\n');
    if (firstNl >= 0) {
      text = text.substring(firstNl + 1).trim();
    } else {
      text = text.replaceFirst(RegExp(r'^```[a-zA-Z0-9_-]*'), '').trim();
    }
    if (text.endsWith('```')) {
      text = text.substring(0, text.length - 3).trim();
    }
  }

  dynamic decoded;
  try {
    decoded = jsonDecode(text);
  } catch (_) {
    decoded = null;
  }
  if (decoded is Map<String, dynamic>) return decoded;

  // Fallback: extract the first {...} block (prose-wrapped completions).
  final start = text.indexOf('{');
  final end = text.lastIndexOf('}');
  if (start >= 0 && end > start) {
    try {
      final block = jsonDecode(text.substring(start, end + 1));
      if (block is Map<String, dynamic>) return block;
    } catch (_) {
      return null;
    }
  }
  return null;
}

String _cap(String s, int max) =>
    s.length <= max ? s : s.substring(0, max);

// ---------------------------------------------------------------------------
// App wiring
// ---------------------------------------------------------------------------

/// The app-wide [MemoryDistiller], wired to the CURRENT backend at first use:
///
/// - Private Mode (toggle on AND on-device model installed) -> local
///   flutter_gemma one-shot via [localDistillGenerator].
/// - Server mode -> [ServerDistillTransport] pointed at the PRODUCT server's
///   `/api/distill` passthrough (the app's own base URL, derived exactly like
///   `HttpChatRepository.baseUrl()`), which stores nothing.
///
/// This is THE test seam for the ChatNotifier distillation hook: tests
/// override it with a recording fake (see chat_notifier_memory_test.dart), so
/// no network or model is ever touched in notifier tests.
final distillerProvider = Provider<MemoryDistiller>((ref) {
  final privateMode = ref.watch(privateModeActiveProvider);
  return MemoryDistiller(
    transport: DistillTransport.forBackend(
      privateMode: privateMode,
      serverBaseUrl: ref.watch(appConfigProvider).baseUrl,
      client: ref.watch(httpClientProvider),
      localGenerator: localDistillGenerator(privateModeActive: privateMode),
    ),
  );
});

/// Best-effort kebab-case slug from a title (used only when the model omitted
/// the id — Task 3's dedupe keys off thread.hash anyway).
String _slugify(String title) {
  final slug = title
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '-')
      .replaceAll(RegExp(r'^-+|-+$'), '');
  return slug.isEmpty ? 'thread' : slug;
}
