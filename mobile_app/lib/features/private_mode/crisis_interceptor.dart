/// Deterministic crisis-safety layer for Private Mode.
///
/// The server model runs behind a strong system prompt; a small on-device
/// model is likelier to miss crisis cues, so this check runs BEFORE the model
/// and its output is prepended to the reply regardless of what the model says.
/// Keyword-based on purpose: predictable, auditable, offline.
library;

const List<String> _crisisPhrases = [
  'kill myself',
  'killing myself',
  'suicide',
  'suicidal',
  'end my life',
  'end it all',
  'want to die',
  'wanna die',
  'better off dead',
  'hurt myself',
  'harm myself',
  'self harm',
  'self-harm',
  'overdose',
  'od on',
];

/// Returns true when [message] contains a crisis cue.
bool isCrisisMessage(String message) {
  final lower = message.toLowerCase();
  return _crisisPhrases.any(lower.contains);
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
