/// Deterministic crisis-safety layer for Private Mode.
///
/// The server model runs behind a strong system prompt; a small on-device
/// model is likelier to miss crisis cues, so this check runs BEFORE the model
/// and its output is prepended to the reply regardless of what the model says.
/// Keyword-based on purpose: predictable, auditable, offline.
library;

final List<RegExp> _crisisPatterns = [
  RegExp(r'\bkill(ing)?\s+myself\b'),
  RegExp(r'\bsuicid(e|al)\b'),
  RegExp(r'\bend\s+(my\s+life|it\s+all)\b'),
  RegExp(r'\b(want|wanna)\s+to\s+die\b'),
  RegExp(r'\bbetter\s+off\s+dead\b'),
  RegExp(r'\b(hurt|harm)(ing)?\s+myself\b'),
  RegExp(r'\bself[\s-]?harm\b'),
  RegExp(r'\boverdos(e|ing|ed)\b'),
];

/// Returns true when [message] contains a crisis cue. Word-boundary regexes
/// on purpose — bare substrings misfire badly here (e.g. "od on" inside
/// "god on", common in recovery talk).
bool isCrisisMessage(String message) {
  final lower = message.toLowerCase();
  return _crisisPatterns.any((p) => p.hasMatch(lower));
}

/// Fixed, model-independent crisis note (mirrors the server prompt's
/// helpline-first guidance and the app's crisis sheet).
const String crisisPreamble = '''
**You don't have to carry this alone — talk to someone right now:**

- **AA 24-Hour Helpline: (212) 647-1680** — a sober member will pick up, any hour.
- Tap **Find a meeting** at the bottom of the screen; there are meetings online right now.
- If you are in immediate danger, call **911**.

---

''';
