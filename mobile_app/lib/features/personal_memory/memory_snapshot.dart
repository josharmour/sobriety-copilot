// FR11 Task 4 — memory snapshot builder + thread resume prompts.
//
// Pure, I/O-free module (no Riverpod, no flutter imports, no platform calls).
// It takes this module's own DTO — MemorySnapshotInput — deliberately NOT
// `PersonalMemory`, so the model file and this builder stay decoupled; the
// chat_notifier agent maps PersonalMemory -> MemorySnapshotInput at the call
// site.
//
// Privacy contract: the string produced by buildClientContextSnapshot rides the
// existing `client_context` request field for server chat and the
// "About this person:" note in local (Private Mode) prompts. The server stores
// nothing — it is a stateless pass-through. Memory never leaves the device
// except through those prompt channels, and the snapshot is capped (<= 400
// chars by default) and self-marked "do not recite it verbatim."

/// A single open topic the user was working on, as seen by the snapshot
/// builder. Only [resolved] == false threads are eligible for injection, and
/// among those only the one with the most recent [updatedAt] is rendered.
class ThreadRef {
  const ThreadRef({
    required this.title,
    this.lastDetail = '',
    required this.updatedAt,
    this.resolved = false,
  });

  final String title;

  /// Short "where we left off" note; may be empty.
  final String lastDetail;

  final DateTime updatedAt;

  /// True once the user marks the thread handled — excluded from snapshots.
  final bool resolved;
}

/// Decoupled input for the snapshot builder. Field names mirror the Personal
/// Memory model so the mapping agent's job is a mechanical copy.
class MemorySnapshotInput {
  const MemorySnapshotInput({
    this.triggers = const [],
    this.goal,
    this.factTexts = const [],
    this.threads = const [],
  });

  /// Situational triggers the user asked to be reminded of.
  final List<String> triggers;

  /// Current recovery goal, if any.
  final String? goal;

  /// Durable facts about the user, most relevant first (top 2 are rendered).
  final List<String> factTexts;

  /// Open threads; only unresolved ones count and only the most recent shows.
  final List<ThreadRef> threads;
}

/// Marker appended to every non-empty snapshot. Private, but its exact text is
/// part of the FR11 prompt contract — see memory_snapshot_test.dart.
const String _suffix =
    '(This is private memory from their device - use it if relevant, do not recite it verbatim.)';

/// Builds the compact snapshot injected into `client_context` (server chat)
/// and the "About this person" note (Private Mode).
///
/// Rendering, one line per section, highest priority first:
///   1. `Currently discussing: <title>[ — <lastDetail>]` — only the most
///      recent unresolved thread (by [ThreadRef.updatedAt], descending).
///   2. `Triggers: a, b`
///   3. `Goal: <goal>`
///   4. up to 2 top [MemorySnapshotInput.factTexts], bare text.
///
/// Lines are joined with `; ` and, whenever the result is non-empty, the
/// non-recitable [_suffix] is appended after a single space. The TOTAL
/// (sections + suffix) never exceeds [maxChars]: when over budget the
/// lowest-priority sections are dropped first (facts, then goal, then
/// triggers, then the thread's em-dash detail, keeping the bare thread
/// title); if a single surviving section alone still busts the cap its text
/// is truncated with an ellipsis so the suffix still fits. Returns the empty
/// string when there is nothing to inject at all.
String buildClientContextSnapshot(
  MemorySnapshotInput input, {
  int maxChars = 400,
}) {
  final thread = _latestUnresolvedThread(input.threads);
  final triggers = _nonBlank(input.triggers);
  final goal = _trimToNull(input.goal);
  final facts = _nonBlank(input.factTexts);

  final lines = <String>[
    if (thread != null)
      'Currently discussing: ${thread.title.trim()}'
          '${thread.lastDetail.trim().isEmpty ? '' : ' — ${thread.lastDetail.trim()}'}',
    if (triggers.isNotEmpty) 'Triggers: ${triggers.join(', ')}',
    if (goal != null) 'Goal: $goal',
    ...facts.take(2),
  ];
  if (lines.isEmpty) return '';

  String withSuffix(List<String> sections) => '${sections.join('; ')} $_suffix';

  // Drop the lowest-priority (tail) sections until the whole thing fits.
  var keep = lines;
  var out = withSuffix(keep);
  while (keep.length > 1 && out.length > maxChars) {
    keep = keep.sublist(0, keep.length - 1);
    out = withSuffix(keep);
  }
  if (out.length <= maxChars) return out;

  // One section survives and still busts the cap. If it is the thread line
  // still carrying its em-dash detail, shed the detail before truncating.
  var survivor = keep.single;
  if (survivor.startsWith('Currently discussing: ')) {
    final dash = survivor.indexOf(' — ');
    if (dash > 0) {
      final bare = survivor.substring(0, dash);
      final bareOut = withSuffix([bare]);
      if (bareOut.length <= maxChars) return bareOut;
      survivor = bare;
    }
  }

  // Last resort: truncate the surviving text with an ellipsis so the suffix
  // still fits under the cap.
  final textBudget = maxChars - _suffix.length - 1; // space before the suffix
  if (textBudget >= 4 && survivor.length > textBudget) {
    return '${survivor.substring(0, textBudget - 3)}... $_suffix';
  }
  return withSuffix([survivor]);
}

/// Seeds a resumed conversation's first message: names the topic (title
/// lowercased except its first letter) and the last known detail. When
/// [ThreadRef.lastDetail] is empty the em-dash clause is dropped.
String resumePromptFor(ThreadRef t) {
  final title = _sentenceCase(t.title.trim());
  final detail = t.lastDetail.trim();
  final head = 'Pick up where we left off: we were talking about $title';
  if (detail.isEmpty) return '$head Can you help me keep going?';
  return '$head — $detail Can you help me keep going?';
}

/// True iff the input carries anything worth injecting: any non-blank
/// trigger, goal, or fact text, or any unresolved thread. A resolved-only
/// thread and blank/whitespace fields do not count.
bool hasAnythingToInject(MemorySnapshotInput input) {
  if (input.triggers.any((t) => t.trim().isNotEmpty)) return true;
  if (input.goal != null && input.goal!.trim().isNotEmpty) return true;
  if (input.factTexts.any((f) => f.trim().isNotEmpty)) return true;
  return input.threads.any(
    (t) => !t.resolved && t.title.trim().isNotEmpty,
  );
}

ThreadRef? _latestUnresolvedThread(List<ThreadRef> threads) {
  ThreadRef? best;
  for (final t in threads) {
    if (t.resolved || t.title.trim().isEmpty) continue;
    if (best == null || t.updatedAt.isAfter(best.updatedAt)) best = t;
  }
  return best;
}

List<String> _nonBlank(Iterable<String> values) =>
    values.map((v) => v.trim()).where((v) => v.isNotEmpty).toList();

String? _trimToNull(String? value) {
  final v = value?.trim() ?? '';
  return v.isEmpty ? null : v;
}

String _sentenceCase(String value) {
  if (value.isEmpty) return value;
  final lowered = value.toLowerCase();
  return lowered[0].toUpperCase() + lowered.substring(1);
}
