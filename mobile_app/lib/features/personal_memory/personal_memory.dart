import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/providers.dart';

/// FR11 personal companion memory.
///
/// Fully on-device: a [PersonalProfile] (curated fields), a capped list of
/// distilled [MemoryFact]s about the person, and a capped list of open
/// [MemoryThread]s (unfinished topics the assistant may resume later).
/// Persisted as one JSON blob under [PersonalMemoryNotifier.prefsKey];
/// never leaves the device.
///
/// Stability note: keys are versioned (`personal_memory_v1`). Changing the
/// schema means bumping the key and migrating, not mutating in place.

const int kMaxFacts = 100;
const int kMaxThreads = 12;
const int kFactTextMax = 120;
const int kThreadTitleMax = 50;
const int kThreadDetailMax = 120;

/// Similarity at or above which two facts count as the same fact.
const double kFactDedupeThreshold = 0.9;

int _idSeq = 0;

/// Unique id: microseconds-since-epoch timestamp + monotonic counter, so two
/// ids generated within the same microsecond can never collide.
String _nextId(String prefix) {
  _idSeq = (_idSeq + 1) & 0x7fffffff;
  return '${prefix}_${DateTime.now().microsecondsSinceEpoch}_$_idSeq';
}

String _cap(String s, int max) => s.length <= max ? s : s.substring(0, max);

/// A single durable fact about the person, distilled from a conversation
/// (never a verbatim message body).
class MemoryFact {
  final String id;
  final String text;
  final DateTime createdAt;
  final String sourceConversationId;

  const MemoryFact({
    required this.id,
    required this.text,
    required this.createdAt,
    required this.sourceConversationId,
  });

  factory MemoryFact.fromJson(Map<String, dynamic> json) => MemoryFact(
    id: (json['id'] as String?) ?? '',
    text: (json['text'] as String?) ?? '',
    createdAt:
        DateTime.tryParse((json['created_at'] as String?) ?? '') ??
        DateTime.fromMillisecondsSinceEpoch(0),
    sourceConversationId: (json['source_conversation_id'] as String?) ?? '',
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'text': text,
    'created_at': createdAt.toIso8601String(),
    'source_conversation_id': sourceConversationId,
  };
}

/// An open (or resolved) topic the assistant may pick up in a later
/// conversation. `resolved` defaults to false.
class MemoryThread {
  final String id;
  final String title; // short (~50 chars)
  final String lastDetail; // short (~120 chars) next-step note
  final DateTime updatedAt;
  final bool resolved;

  const MemoryThread({
    required this.id,
    required this.title,
    this.lastDetail = '',
    required this.updatedAt,
    this.resolved = false,
  });

  factory MemoryThread.fromJson(Map<String, dynamic> json) => MemoryThread(
    id: (json['id'] as String?) ?? '',
    title: (json['title'] as String?) ?? '',
    lastDetail: (json['last_detail'] as String?) ?? '',
    updatedAt:
        DateTime.tryParse((json['updated_at'] as String?) ?? '') ??
        DateTime.fromMillisecondsSinceEpoch(0),
    resolved: (json['resolved'] as bool?) ?? false,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'last_detail': lastDetail,
    'updated_at': updatedAt.toIso8601String(),
    'resolved': resolved,
  };
}

/// Curated profile fields. All optional; `triggers` defaults to empty.
class PersonalProfile {
  final String? sponsor;
  final String? homeGroup;
  final String? goal;
  final List<String> triggers;

  const PersonalProfile({
    this.sponsor,
    this.homeGroup,
    this.goal,
    this.triggers = const [],
  });

  factory PersonalProfile.fromJson(Map<String, dynamic> json) {
    final rawTriggers = json['triggers'];
    return PersonalProfile(
      sponsor: json['sponsor'] as String?,
      homeGroup: json['home_group'] as String?,
      goal: json['goal'] as String?,
      triggers:
          rawTriggers is List
              ? List<String>.unmodifiable(rawTriggers.whereType<String>())
              : const [],
    );
  }

  Map<String, dynamic> toJson() => {
    'sponsor': sponsor,
    'home_group': homeGroup,
    'goal': goal,
    'triggers': triggers,
  };

  /// Copy-with: a null argument keeps the existing value.
  PersonalProfile copyWith({
    String? sponsor,
    String? homeGroup,
    String? goal,
    List<String>? triggers,
  }) => PersonalProfile(
    sponsor: sponsor ?? this.sponsor,
    homeGroup: homeGroup ?? this.homeGroup,
    goal: goal ?? this.goal,
    triggers: triggers ?? this.triggers,
  );
}

/// Normalized token set for fact dedupe: lowercase, punctuation stripped,
/// whitespace collapsed.
Set<String> _normalizedTokens(String text) {
  final t =
      text
          .toLowerCase()
          .replaceAll(RegExp(r'[^\p{L}\p{N}\s]', unicode: true), ' ')
          .replaceAll(RegExp(r'\s+'), ' ')
          .trim();
  if (t.isEmpty) return const {};
  return t.split(' ').toSet();
}

/// Token-set Jaccard similarity in [0, 1].
double _tokenJaccard(Set<String> a, Set<String> b) {
  if (a.isEmpty && b.isEmpty) return 1;
  if (a.isEmpty || b.isEmpty) return 0;
  final union = a.union(b).length;
  if (union == 0) return 1;
  return a.intersection(b).length / union;
}

/// Immutable aggregate record. Never mutate in place: every change returns a
/// new [PersonalMemory] via the `with*` methods.
class PersonalMemory {
  final PersonalProfile profile;
  final List<MemoryFact> facts; // append order (oldest first), cap 100
  final List<MemoryThread> threads; // cap 12, LRU by updatedAt on overflow

  const PersonalMemory({
    this.profile = const PersonalProfile(),
    this.facts = const [],
    this.threads = const [],
  });

  factory PersonalMemory.fromJson(Map<String, dynamic> json) {
    var m = PersonalMemory(
      profile:
          json['profile'] is Map
              ? PersonalProfile.fromJson(
                Map<String, dynamic>.from(json['profile'] as Map),
              )
              : const PersonalProfile(),
    );
    final rawFacts = json['facts'];
    if (rawFacts is List) {
      final facts = <MemoryFact>[
        for (final e in rawFacts.whereType<Map>())
          MemoryFact.fromJson(Map<String, dynamic>.from(e)),
      ];
      m = m._withFacts(facts);
    }
    final rawThreads = json['threads'];
    if (rawThreads is List) {
      final threads = <MemoryThread>[
        for (final e in rawThreads.whereType<Map>())
          MemoryThread.fromJson(Map<String, dynamic>.from(e)),
      ];
      m = m._withThreads(threads);
    }
    return m;
  }

  Map<String, dynamic> toJson() => {
    'profile': profile.toJson(),
    'facts': facts.map((f) => f.toJson()).toList(),
    'threads': threads.map((t) => t.toJson()).toList(),
  };

  /// Adds a distilled fact: trims, caps at 120 chars, then rejects it as a
  /// duplicate when any existing fact's normalized token-set Jaccard
  /// similarity is >= [kFactDedupeThreshold]. A duplicate (or blank text)
  /// returns this instance unchanged.
  PersonalMemory withFactAdded(
    String text, {
    required String sourceConversationId,
  }) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return this;
    final capped = _cap(trimmed, kFactTextMax);
    final tokens = _normalizedTokens(capped);
    if (tokens.isEmpty) return this;
    for (final f in facts) {
      if (_tokenJaccard(tokens, _normalizedTokens(f.text)) >=
          kFactDedupeThreshold) {
        return this;
      }
    }
    final next = List<MemoryFact>.of(facts)..add(
      MemoryFact(
        id: _nextId('fact'),
        text: capped,
        createdAt: DateTime.now(),
        sourceConversationId: sourceConversationId,
      ),
    );
    return _withFacts(next);
  }

  /// Upsert a thread: an existing [id] updates its title (when non-empty),
  /// detail (when non-null and non-empty), bumps [MemoryThread.updatedAt] and
  /// clears `resolved`; an unknown id appends a new thread. Overflow evicts
  /// the least recently updated thread.
  PersonalMemory withThreadUpdated(String id, String title, String? detail) {
    final index = threads.indexWhere((t) => t.id == id);
    final now = _nowStrictlyAfter(threads.map((t) => t.updatedAt));
    if (index >= 0) {
      final old = threads[index];
      final newTitle = title.trim();
      final newDetail = detail?.trim() ?? '';
      final updated = MemoryThread(
        id: old.id,
        title:
            newTitle.isNotEmpty ? _cap(newTitle, kThreadTitleMax) : old.title,
        lastDetail:
            newDetail.isNotEmpty
                ? _cap(newDetail, kThreadDetailMax)
                : old.lastDetail,
        updatedAt: now,
        resolved: false,
      );
      final next = List<MemoryThread>.of(threads)..[index] = updated;
      return _withThreads(next);
    }
    final next = List<MemoryThread>.of(threads)..add(
      MemoryThread(
        id: id,
        title: _cap(title.trim(), kThreadTitleMax),
        lastDetail: detail == null ? '' : _cap(detail.trim(), kThreadDetailMax),
        updatedAt: now,
      ),
    );
    return _withThreads(next);
  }

  /// Marks a thread resolved (no timestamp bump). Unknown id: unchanged.
  PersonalMemory withThreadResolved(String id) {
    final index = threads.indexWhere((t) => t.id == id);
    if (index < 0) return this;
    final old = threads[index];
    final next = List<MemoryThread>.of(threads)
      ..[index] = MemoryThread(
        id: old.id,
        title: old.title,
        lastDetail: old.lastDetail,
        updatedAt: old.updatedAt,
        resolved: true,
      );
    return _withThreads(next);
  }

  /// Copy-with on the profile: null keeps the existing value.
  PersonalMemory withProfile({
    String? sponsor,
    String? homeGroup,
    String? goal,
    List<String>? triggers,
  }) => PersonalMemory(
    profile: profile.copyWith(
      sponsor: sponsor,
      homeGroup: homeGroup,
      goal: goal,
      triggers: triggers,
    ),
    facts: facts,
    threads: threads,
  );

  /// Removes the fact with [id]. Unknown id: unchanged instance.
  PersonalMemory withFactRemoved(String id) {
    if (!facts.any((f) => f.id == id)) return this;
    return _withFacts(facts.where((f) => f.id != id).toList());
  }

  /// Removes the thread with [id]. Unknown id: unchanged instance.
  PersonalMemory withThreadRemoved(String id) {
    if (!threads.any((t) => t.id == id)) return this;
    return _withThreads(threads.where((t) => t.id != id).toList());
  }

  /// Forget everything: profile, facts, and threads all reset to defaults.
  PersonalMemory withAllCleared() => const PersonalMemory();

  /// Strictly-increasing clock: guarantees a total order on thread
  /// updatedAt values so LRU eviction is deterministic.
  static DateTime _nowStrictlyAfter(Iterable<DateTime> existing) {
    var t = DateTime.now();
    for (final e in existing) {
      if (!t.isAfter(e)) {
        t = e.add(const Duration(microseconds: 1));
      }
    }
    return t;
  }

  PersonalMemory _withFacts(List<MemoryFact> next) {
    if (next.length > kMaxFacts) {
      next = next.sublist(next.length - kMaxFacts);
    }
    return PersonalMemory(
      profile: profile,
      facts: List.unmodifiable(next),
      threads: threads,
    );
  }

  PersonalMemory _withThreads(List<MemoryThread> next) {
    while (next.length > kMaxThreads) {
      // Evict the least recently updated (minimum updatedAt).
      MemoryThread? lru;
      for (final t in next) {
        if (lru == null || t.updatedAt.isBefore(lru.updatedAt)) lru = t;
      }
      next = next.where((t) => t.id != lru!.id).toList();
    }
    return PersonalMemory(
      profile: profile,
      facts: facts,
      threads: List.unmodifiable(next),
    );
  }
}

/// Owns [PersonalMemory], loading it from SharedPreferences in [build] and
/// persisting the whole record as one JSON blob on every mutation.
/// Mirrors the FR4 MoodNotifier pattern.
class PersonalMemoryNotifier extends Notifier<PersonalMemory> {
  static const String prefsKey = 'personal_memory_v1';

  @override
  PersonalMemory build() {
    final raw = ref.read(sharedPreferencesProvider).getString(prefsKey);
    if (raw == null || raw.isEmpty) return const PersonalMemory();
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return const PersonalMemory();
      return PersonalMemory.fromJson(Map<String, dynamic>.from(decoded));
    } catch (_) {
      // Corrupted blob: start empty, never throw.
      return const PersonalMemory();
    }
  }

  Future<void> addFact(String text, String sourceConversationId) =>
      _mutate(
        state.withFactAdded(text, sourceConversationId: sourceConversationId),
      );

  Future<void> upsertThread(String id, String title, String? detail) =>
      _mutate(state.withThreadUpdated(id, title, detail));

  Future<void> resolveThread(String id) =>
      _mutate(state.withThreadResolved(id));

  Future<void> updateProfile({
    String? sponsor,
    String? homeGroup,
    String? goal,
    List<String>? triggers,
  }) => _mutate(
    state.withProfile(
      sponsor: sponsor,
      homeGroup: homeGroup,
      goal: goal,
      triggers: triggers,
    ),
  );

  Future<void> removeFact(String id) => _mutate(state.withFactRemoved(id));

  Future<void> removeThread(String id) => _mutate(state.withThreadRemoved(id));

  /// Wipes profile, facts, and threads, and persists the empty record.
  Future<void> forgetAll() => _mutate(state.withAllCleared());

  Future<void> _mutate(PersonalMemory next) async {
    if (identical(next, state)) return; // no-op (e.g. duplicate fact)
    state = next;
    await ref
        .read(sharedPreferencesProvider)
        .setString(prefsKey, jsonEncode(state.toJson()));
  }
}

/// App-wide memory provider. Registered here (not in providers.dart) so the
/// feature module is self-contained.
final personalMemoryProvider =
    NotifierProvider<PersonalMemoryNotifier, PersonalMemory>(
      PersonalMemoryNotifier.new,
    );
