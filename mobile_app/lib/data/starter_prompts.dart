/// Recovery-oriented starter prompts and daily reflections.
///
/// Mirrors the web app's `STARTER_PROMPTS`, `EVERGREEN_PROMPTS`, `FAQ_PROMPTS`
/// and `REFLECTIONS` (see static/index.html). The prompts are bucketed by time
/// of day so the chat screen can surface contextually appropriate suggestions
/// when the conversation is empty.
library;

/// Time-bucketed starter prompts mirroring the web app
/// (keys: 'morning','day','evening','late').
const Map<String, List<String>> kStarterPrompts = {
  'morning': [
    "Help me set an intention for today's recovery.",
    "What does the literature say about gratitude in early sobriety?",
    "Share a passage about starting the day with prayer or meditation.",
    "What is the Set Aside Prayer?",
    "How do I do a morning step eleven?",
    "What does it mean to turn my will and life over each morning?",
    "Show me a reading on willingness to start the day.",
    "How do I begin the day without a drink or a drug?",
    "What is the Third Step Prayer?",
    "What does 'thy will, not mine, be done' mean in practice?",
    "How do I get out of self in the morning?",
    "Share a daily reflection about acceptance.",
    "What does the Big Book say about pausing when agitated?",
    "How do I prepare myself spiritually for the day ahead?",
    "What are some morning meditation practices in recovery?",
    "How do I face a difficult day sober?",
    "What does the literature say about a daily reprieve?",
    "Help me think about service for today.",
    "What's the best way to start a sponsor call?",
    "What is the meaning of 'easy does it'?",
  ],
  'day': [
    "What are the twelve steps and how do they work?",
    "How do I find a sponsor?",
    "What does the Big Book say about resentment?",
    "How does a higher power work if I'm not religious?",
    "What is the difference between a dry drunk and real sobriety?",
    "What is a moral inventory and why is it important?",
    "How do I work with a sponsor on the steps?",
    "What does the literature say about service work?",
    "Explain the spiritual experience promised in the steps.",
    "How do I make amends without doing more harm?",
    "What is the difference between Step 4 and Step 10?",
    "How do I work Step Five honestly?",
    "What is meant by 'character defects' in Step 6?",
    "Walk me through Step Seven and the Seventh Step Prayer.",
    "What does Step Eight ask of us?",
    "What does Step Nine say about direct amends?",
    "How does Step Eleven differ from Step Three?",
    "What is the Twelfth Step and how do I carry the message?",
    "What does the literature say about humility?",
    "What does the program say about self-pity?",
    "What is the role of a home group?",
    "Why is anonymity at the core of A.A.?",
    "What are the Twelve Traditions and why do they matter?",
    "Tell me about the history of A.A.",
    "What does 'we agnostics' say about belief?",
    "What is the chapter 'How It Works' really teaching?",
    "What does the Big Book mean by 'half measures'?",
    "Tell me about the Promises in the Big Book.",
  ],
  'evening': [
    "How do I do a tenth step inventory at the end of the day?",
    "What does the literature say about restless, irritable, and discontent?",
    "How do I let go of a hard day?",
    "What is acceptance in recovery?",
    "Show me a passage about humility.",
    "How do I forgive myself for the day?",
    "What does the literature say about ending the day in prayer?",
    "Help me reflect on how I treated others today.",
    "Tell me a story about an early member who relapsed and came back.",
    "What does 'the maintenance of our spiritual condition' mean?",
    "How do I take stock honestly without self-flagellation?",
    "What is the difference between guilt and shame in recovery?",
    "Help me think about an apology I owe someone.",
    "What does the program say about being of maximum service?",
    "How do I close the day in gratitude?",
    "What does the Big Book say about taking it easy on ourselves?",
    "Help me reflect on whether I've been honest today.",
    "Show me a reading about peace at the end of a hard day.",
    "What does 'constant thought of others' look like in practice?",
    "How do I make a list of who I owe amends to?",
  ],
  'late': [
    "How do I deal with cravings and urges to drink right now?",
    "What does the literature say about the first 24 hours?",
    "How do I get through tonight one moment at a time?",
    "What does HALT mean in recovery?",
    "What can I do instead of using right now?",
    "Share a passage for when I can't sleep.",
    "What does the Big Book say about playing the tape forward?",
    "How do I sit with discomfort without using?",
    "Help me think through a craving step by step.",
    "What's a phone call I can make right now?",
    "What does the literature say about surviving a hard night?",
    "Show me a passage about powerlessness for tonight.",
    "What does it mean to surrender to win?",
    "Read me something about hope when I feel hopeless.",
    "What did Bill W. say about white-knuckling sobriety?",
    "How do I get through a craving without acting on it?",
    "What's a quick spot-check inventory I can do tonight?",
    "Help me write out a gratitude list right now.",
    "What does 'just for tonight' mean?",
    "Help me settle down enough to sleep.",
  ],
};

/// Evergreen prompts that apply at any time of day (mirrors web app).
const List<String> _kEvergreenPrompts = [
  "What is the difference between a dry drunk and real sobriety?",
  "How do I deal with anger in recovery?",
  "What does the literature say about loneliness?",
  "Help me understand surrender.",
  "What is one thing I can do today for my recovery?",
  "Show me a passage about hope.",
  "What does the Big Book say about fear?",
  "How do alcoholics differ from heavy drinkers, per the Doctor's Opinion?",
  "Tell me about the role of prayer and meditation in recovery.",
  "What does the literature say about complacency?",
  "How do I keep my recovery fresh after years of sobriety?",
  "What is meant by 'rigorous honesty'?",
  "Help me understand the term 'spiritual awakening'.",
  "What does the program say about envy and comparison?",
  "How do I work with a newcomer?",
  "What does 'first things first' really mean?",
];

/// Daily reflection quotes shown above starter prompts.
const List<String> kReflections = [
  "One day at a time.",
  "Progress, not perfection.",
  "First things first.",
  "This too shall pass.",
  "Easy does it — but do it.",
  "Let go and let God.",
  "Live and let live.",
];

/// All prompts flattened & de-duplicated (case-insensitive, order-preserving).
final List<String> kAllStarterPrompts = _flattenPrompts();

List<String> _flattenPrompts() {
  final all = <String>[
    ...kStarterPrompts['morning']!,
    ...kStarterPrompts['day']!,
    ...kStarterPrompts['evening']!,
    ...kStarterPrompts['late']!,
    ..._kEvergreenPrompts,
  ];
  final seen = <String>{};
  final out = <String>[];
  for (final p in all) {
    final key = p.toLowerCase().trim();
    if (seen.add(key)) out.add(p);
  }
  return List.unmodifiable(out);
}

/// Returns the bucket appropriate for [now] (defaults to DateTime.now()):
/// morning 4–11, day 11–17, evening 17–22, late 22–4.
List<String> starterPromptsForNow([DateTime? now]) {
  final hour = (now ?? DateTime.now()).hour;
  final String key;
  if (hour >= 4 && hour < 11) {
    key = 'morning';
  } else if (hour >= 11 && hour < 17) {
    key = 'day';
  } else if (hour >= 17 && hour < 22) {
    key = 'evening';
  } else {
    key = 'late';
  }
  return kStarterPrompts[key]!;
}

/// Deterministic daily reflection (index by day-of-year % length).
String reflectionForToday([DateTime? now]) {
  final date = now ?? DateTime.now();
  final dayOfYear = date.difference(DateTime(date.year, 1, 1)).inDays;
  return kReflections[dayOfYear % kReflections.length];
}
