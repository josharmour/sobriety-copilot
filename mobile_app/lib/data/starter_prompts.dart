/// Recovery-oriented starter prompts and daily reflections.
///
/// Prompts are bucketed by time of day and merged with an evergreen pool, so
/// the empty-chat screen surfaces contextually appropriate suggestions. A
/// persisted no-repeat window ([pickStarterPrompts]) rotates through the
/// whole pool before anything comes back around — a user shouldn't see the
/// same suggestion twice for a long while. (Conversation follow-ups and
/// "continue your study" cards are separate and unaffected.)
library;

import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

/// Time-bucketed starter prompts (keys: 'morning','day','evening','late').
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
    "What does 'on awakening' ask us to do before the day starts?",
    "How do I ask for help with a day I'm dreading?",
    "Give me one sentence from the literature to carry today.",
    "How do I keep this morning's serenity through a busy day?",
    "What does the literature say about facing work sober?",
    "I woke up anxious — what does the program suggest?",
    "I woke up grateful today. How do I build on that?",
    "How do old-timers describe their morning routine?",
    "What's a short prayer I can say before getting out of bed?",
    "How do I plan my day around a meeting?",
    "What does the Big Book say about self-will run riot?",
    "I have a resentment already this morning. Where do I start?",
    "How do I greet a day when nothing feels wrong — and not get complacent?",
    "What does 'fit spiritual condition' actually require of me daily?",
    "Show me something about courage for a hard conversation today.",
    "What would a sponsor tell me before a stressful morning?",
    "How is a morning inventory different from a nightly one?",
    "What does the St. Francis Prayer teach about starting the day?",
    "Why do people say 'don't leave before the miracle happens'?",
    "What page should I read with my coffee this morning?",
    "How do I remember my last drunk without living in it?",
    "What does the literature say about starting over after a bad day?",
    "Help me pray for someone I resent this morning.",
    "What's the difference between planning my day and projecting?",
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
    "How do I handle a coworker who drinks at lunch?",
    "What does the literature say about money and financial fear?",
    "Can I keep friendships with people who still drink?",
    "What does the Big Book say about the family afterward?",
    "How did Bill W. and Dr. Bob meet?",
    "What is the Doctor's Opinion and why does it open the Big Book?",
    "Explain 'the alcoholic is like a tornado roaring through the lives of others.'",
    "What is Tradition Three and why does it matter to newcomers?",
    "How do the steps treat willpower — is it useless?",
    "What does the program say about romantic relationships in early recovery?",
    "How do I tell my kids about my recovery?",
    "What does the literature say about work and ambition?",
    "What's a Big Book study versus a discussion meeting?",
    "How do I chair a meeting for the first time?",
    "What does sponsorship ask of the sponsor?",
    "Why do we say 'principles before personalities'?",
    "What does the literature say about perfectionism?",
    "How do I handle criticism without picking up?",
    "What is emotional sobriety?",
    "What did Bill W. write about depression and emotional sobriety?",
    "How do I stay sober through a divorce or breakup?",
    "What does the program suggest about big life decisions in year one?",
    "Explain the phrase 'contempt prior to investigation.'",
    "What does 'more will be revealed' mean?",
    "How do I study a step — not just read it?",
    "What questions should I ask a potential sponsor?",
    "What does the literature say about telling my story?",
    "How do the Twelve Concepts fit into service?",
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
    "Walk me through the 'when we retire at night' review.",
    "I snapped at someone today. What now?",
    "What does the literature say about envy of people who can drink?",
    "How do I unwind sober after a stressful day?",
    "I skipped my meeting today — how do I get back on track?",
    "What does the evening hold for people in the fellowship — what did early members do at night?",
    "Show me a passage about trusting God with tomorrow.",
    "How do I stop replaying an argument in my head?",
    "What does the program say about resenting my job?",
    "Help me review my motives from today, not just my actions.",
    "What's the difference between reflection and rumination?",
    "I felt left out tonight. What does the literature say about belonging?",
    "How do I celebrate a good day without getting complacent?",
    "What did I pack into the stream of life today?",
    "Show me something about patience with my family.",
    "How do I set down the day's fear before bed?",
    "What does the literature say about loneliness in the evening hours?",
    "Tonight I'm restless. Read me something steadying.",
    "How do couples in recovery keep evenings peaceful?",
    "What does the Big Book say about wallowing in remorse?",
    "Help me find one thing today that deserves gratitude.",
    "How do I plan tomorrow without white-knuckling it?",
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
    "Why do cravings hit hardest at night?",
    "Read me the Serenity Prayer, slowly, with what each line means.",
    "The house is quiet and my head is loud. What does the program say?",
    "What did early members do on sleepless nights?",
    "Show me a passage about fear of the dark hours.",
    "Is there an online meeting happening right now?",
    "How do I handle being the only one awake and sober?",
    "What does the literature say about insomnia in early recovery?",
    "Give me a prayer for 2 a.m.",
    "I'm lonely tonight. Read me something about the fellowship.",
    "How do I quiet regret enough to rest?",
    "What does 'this too shall pass' really promise?",
    "Talk me through box breathing and a short eleventh-step meditation.",
    "I had a using dream. What does that mean?",
    "What does the Big Book say about the mental blank spot?",
    "Remind me why I quit.",
    "Show me something gentle about self-forgiveness tonight.",
    "How is one night of not drinking a victory?",
    "What would my sponsor say right now?",
    "Read me a passage about the sunlight of the spirit.",
  ],
};

/// Evergreen prompts merged into every bucket's rotation.
const List<String> kEvergreenPrompts = [
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
  "What does the literature say about grief and loss?",
  "How do I handle a family gathering where everyone drinks?",
  "What does the program say about chronic pain and medication?",
  "Explain 'acceptance is the answer to all my problems today.'",
  "What does the literature say about honesty with my doctor?",
  "How do people stay sober through job loss?",
  "What does the Big Book say about fun in sobriety?",
  "How do I travel and stay connected to the program?",
  "What is a sponsee's responsibility?",
  "Show me a passage about courage.",
  "What does the literature say about procrastination and discipline?",
  "How do I know if I'm spiritually blocked?",
  "What's the difference between religion and spirituality in the program?",
  "What does the program say about comparing my insides to others' outsides?",
  "How do I handle praise without ego trouble?",
  "What does the literature say about jealousy in relationships?",
  "Tell me about Dr. Bob's last talk.",
  "What is the 'jumping-off place' the Big Book describes?",
  "Explain 'we will love you until you can love yourself.'",
  "What does the program teach about asking for help?",
  "How do I support a friend who relapsed?",
  "What does the literature say about anonymity on social media?",
  "Show me a passage about patience.",
  "What does 'keep coming back' actually do?",
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
    ...kEvergreenPrompts,
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

/// SharedPreferences key for the rotation window (list of recently shown
/// prompts, oldest first).
const String _kRecentPromptsKey = 'starter_prompts_recent_v1';

/// How many recently-shown prompts stay excluded from the draw. With
/// bucket+evergreen pools of ~80–95, a window of 60 means the rotation walks
/// most of the pool before anything can reappear.
const int _kRecentWindow = 60;

/// Picks [count] starter prompts for the current time of day, excluding
/// anything shown recently (persisted across sessions). Falls back to
/// releasing the oldest half of the window when the pool runs low.
List<String> pickStarterPrompts(
  SharedPreferences prefs, {
  int count = 5,
  DateTime? now,
  Random? random,
}) {
  final rng = random ?? Random();
  final pool = <String>{
    ...starterPromptsForNow(now),
    ...kEvergreenPrompts,
  }.toList();

  var recent = prefs.getStringList(_kRecentPromptsKey) ?? const <String>[];
  var recentSet = recent.toSet();
  var candidates = pool.where((p) => !recentSet.contains(p)).toList();

  // Window too aggressive for this bucket's pool — release the oldest half.
  if (candidates.length < count) {
    recent = recent.sublist(recent.length ~/ 2);
    recentSet = recent.toSet();
    candidates = pool.where((p) => !recentSet.contains(p)).toList();
  }
  if (candidates.length < count) {
    candidates = pool; // Degenerate case (tiny pool): allow anything.
  }

  candidates.shuffle(rng);
  final picked = candidates.take(count).toList();

  final nextRecent = [
    ...recent.where((p) => !picked.contains(p)),
    ...picked,
  ];
  final trimmed = nextRecent.length > _kRecentWindow
      ? nextRecent.sublist(nextRecent.length - _kRecentWindow)
      : nextRecent;
  // Fire-and-forget persistence; the picker itself stays synchronous.
  prefs.setStringList(_kRecentPromptsKey, trimmed);

  return picked;
}

/// Deterministic daily reflection (index by day-of-year % length).
String reflectionForToday([DateTime? now]) {
  final date = now ?? DateTime.now();
  final dayOfYear = date.difference(DateTime(date.year, 1, 1)).inDays;
  return kReflections[dayOfYear % kReflections.length];
}
