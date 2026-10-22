/// Recovery-oriented starter prompts, 92-topic / 1,790+ prompt dynamic catalog,
/// and true-interest signal personalization.
///
/// Prompts are drawn from [kRecoveryTopicCatalog] (92 canonical recovery topics
/// and 2,500+ sub-concepts) and [kStarterPrompts] / [kEvergreenPrompts].
///
/// When the user has genuine query history — queries they typed/dictated/scanned
/// themselves, or starter-initiated conversations where they continued
/// interacting (follow-up turns, saved passages, or saved memory facts) —
/// [pickStarterPrompts] weights the draw toward their active topics and
/// NPMI-connected peer topics while keeping serendipitous time-of-day variety.
/// Single-turn clicks on preloaded starter prompts ("testing the app") receive
/// zero weight so they never skew future recommendations.
library;

import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/topic_prompts_catalog.dart';
import 'package:sobriety_copilot_mobile/features/personal_memory/personal_memory.dart';

export 'package:sobriety_copilot_mobile/data/topic_prompts_catalog.dart';

/// Time-bucketed core starter prompts (keys: 'morning','day','evening','late').
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

/// Map of topic ID -> [RecoveryTopicEntry] for O(1) lookup.
final Map<String, RecoveryTopicEntry> kTopicById = {
  for (final t in kRecoveryTopicCatalog) t.id: t,
};

/// All prompts flattened & de-duplicated across the 92-topic catalog and
/// time-of-day pools (~1,800+ unique recovery prompts).
final List<String> kAllStarterPrompts = _flattenPrompts();

/// Normalized lookup set of all preloaded starter prompts, used to detect
/// whether a conversation's opening message came from a preloaded starter
/// button versus being typed/dictated/scanned by the user.
final Set<String> _kNormalizedStarterSet = {
  for (final p in kAllStarterPrompts) _normalizePromptKey(p),
};

String _normalizePromptKey(String text) {
  return text
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim();
}

List<String> _flattenPrompts() {
  final all = <String>[
    ...kStarterPrompts['morning']!,
    ...kStarterPrompts['day']!,
    ...kStarterPrompts['evening']!,
    ...kStarterPrompts['late']!,
    ...kEvergreenPrompts,
    for (final topic in kRecoveryTopicCatalog) ...topic.prompts,
  ];
  final seen = <String>{};
  final out = <String>[];
  for (final p in all) {
    final key = _normalizePromptKey(p);
    if (seen.add(key)) out.add(p);
  }
  return List.unmodifiable(out);
}

/// Returns true if [text] matches any preloaded starter prompt in the catalog.
bool isKnownStarterPrompt(String text) {
  final key = _normalizePromptKey(text);
  if (key.isEmpty) return false;
  return _kNormalizedStarterSet.contains(key);
}

/// SharedPreferences key tracking prompts explicitly tapped from the starter screen.
const String kTappedStarterPromptsKey = 'starter_prompts_tapped_v1';
const int _kMaxTappedHistory = 300;

/// Records that the user tapped a preloaded starter button.
Future<void> recordStarterPromptTapped(
  SharedPreferences prefs,
  String prompt,
) async {
  final norm = _normalizePromptKey(prompt);
  if (norm.isEmpty) return;
  final existing = prefs.getStringList(kTappedStarterPromptsKey) ?? const <String>[];
  final next = <String>[
    ...existing.where((e) => e != norm),
    norm,
  ];
  final trimmed = next.length > _kMaxTappedHistory
      ? next.sublist(next.length - _kMaxTappedHistory)
      : next;
  await prefs.setStringList(kTappedStarterPromptsKey, trimmed);
}

/// Returns the time bucket name ('morning' | 'day' | 'evening' | 'late') for [now].
String timeBucketForNow([DateTime? now]) {
  final hour = (now ?? DateTime.now()).hour;
  if (hour >= 4 && hour < 11) {
    return 'morning';
  } else if (hour >= 11 && hour < 17) {
    return 'day';
  } else if (hour >= 17 && hour < 22) {
    return 'evening';
  } else {
    return 'late';
  }
}

/// Returns the starter prompt pool appropriate for [now] (defaults to
/// DateTime.now()): morning 4–11, day 11–17, evening 17–22, late 22–4.
/// Combines the core time-bucketed prompts with all catalog topics that have
/// affinity for that time of day.
List<String> starterPromptsForNow([DateTime? now]) {
  final key = timeBucketForNow(now);
  final seen = <String>{};
  final out = <String>[];
  for (final p in kStarterPrompts[key]!) {
    if (seen.add(_normalizePromptKey(p))) out.add(p);
  }
  for (final topic in kRecoveryTopicCatalog) {
    if (topic.timeAffinity == key) {
      for (final p in topic.prompts) {
        if (seen.add(_normalizePromptKey(p))) out.add(p);
      }
    }
  }
  return out;
}

/// Extracts true-interest user messages from local [conversations], filtering
/// out single-turn preloaded starter clicks ("testing the app" signal).
///
/// A conversation's messages are included ONLY if:
/// 1. The user typed/dictated/scanned the query themselves (not a preloaded
///    starter prompt, or included attached photos), OR
/// 2. The user interacted with the conversation after the initial starter
///    prompt was sent ($\ge 2$ user turns, or saved a passage from that chat,
///    or saved a personal memory fact from that chat).
List<({String text, double weight})> extractTrueInterestSignals({
  required List<Conversation> conversations,
  PersonalMemory? memory,
  List<Source> savedPassages = const [],
  SharedPreferences? prefs,
  DateTime? now,
}) {
  final currentTime = now ?? DateTime.now();
  final tappedSet = (prefs?.getStringList(kTappedStarterPromptsKey) ?? const <String>[])
      .toSet();
  final memoryConvIds = <String>{
    if (memory != null)
      for (final f in memory.facts)
        if (f.sourceConversationId.isNotEmpty) f.sourceConversationId,
  };
  final savedSourceKeys = <String>{
    for (final s in savedPassages) '${s.documentKey}|${s.excerpt.trim()}',
  };

  bool isStarterPrompt(String text) {
    final norm = _normalizePromptKey(text);
    return tappedSet.contains(norm) || _kNormalizedStarterSet.contains(norm);
  }

  final signals = <({String text, double weight})>[];

  for (final conv in conversations) {
    final userMsgs = conv.messages
        .where((m) => m.role == 'user' && m.text.trim().isNotEmpty)
        .toList();
    if (userMsgs.isEmpty) continue;

    final hasSavedMemory = memoryConvIds.contains(conv.id);
    var hasSavedPassage = false;
    if (savedSourceKeys.isNotEmpty) {
      for (final m in conv.messages) {
        if (m.role != 'assistant') continue;
        for (final s in m.sources) {
          if (savedSourceKeys.contains('${s.documentKey}|${s.excerpt.trim()}')) {
            hasSavedPassage = true;
            break;
          }
        }
        if (hasSavedPassage) break;
      }
    }

    final firstMsg = userMsgs.first;
    final firstWasPreloadedStarter =
        firstMsg.imageThumbs.isEmpty && isStarterPrompt(firstMsg.text);
    final userInteractedAfterInitial =
        userMsgs.length >= 2 || hasSavedMemory || hasSavedPassage;

    // Crucial filter: if the user merely clicked a preloaded starter prompt and
    // never interacted with the conversation afterward, ignore it completely
    // so "testing the app" clicks do not amplify random starter topics.
    if (firstWasPreloadedStarter && !userInteractedAfterInitial) {
      continue;
    }

    final ageDays = max(
      0,
      currentTime.difference(conv.updatedAt).inHours / 24.0,
    );
    // Smooth 14-day half-life recency decay in [0.25, 1.0].
    final recency = (1.0 / (1.0 + ageDays / 14.0)).clamp(0.25, 1.0);

    // Score the opening message: higher weight if typed by the user themselves,
    // moderate weight if it was a starter prompt that the user followed up on.
    final firstWeight = (firstWasPreloadedStarter ? 1.0 : 2.5) * recency;
    signals.add((text: firstMsg.text, weight: firstWeight));

    // Score all subsequent turns in the conversation (strong engagement signal).
    for (var i = 1; i < userMsgs.length; i++) {
      final msg = userMsgs[i];
      final w = (isStarterPrompt(msg.text) ? 1.25 : 2.25) * recency;
      signals.add((text: msg.text, weight: w));
    }
  }

  // Also incorporate explicit personal memory facts, triggers, goals, and
  // open threads when available — these are high-signal recovery interests.
  if (memory != null) {
    for (final trigger in memory.profile.triggers) {
      if (trigger.trim().isNotEmpty) {
        signals.add((text: trigger, weight: 2.0));
      }
    }
    if (memory.profile.goal != null && memory.profile.goal!.trim().isNotEmpty) {
      signals.add((text: memory.profile.goal!, weight: 2.0));
    }
    for (final fact in memory.facts.reversed.take(25)) {
      if (fact.text.trim().isNotEmpty) {
        signals.add((text: fact.text, weight: 1.5));
      }
    }
    for (final thread in memory.threads) {
      if (!thread.resolved && thread.title.trim().isNotEmpty) {
        signals.add((
          text: '${thread.title} ${thread.lastDetail}',
          weight: 2.25,
        ));
      }
    }
  }

  return signals;
}

/// Scores all 92 recovery topics in [kRecoveryTopicCatalog] against the user's
/// true-interest signals and spreads activation across NPMI peer topics.
Map<String, double> extractTrueInterestTopicScores({
  required List<Conversation> conversations,
  PersonalMemory? memory,
  List<Source> savedPassages = const [],
  SharedPreferences? prefs,
  DateTime? now,
}) {
  final signals = extractTrueInterestSignals(
    conversations: conversations,
    memory: memory,
    savedPassages: savedPassages,
    prefs: prefs,
    now: now,
  );
  if (signals.isEmpty) return const {};

  final directScores = <String, double>{};

  for (final sig in signals) {
    final text = sig.text.toLowerCase();
    for (final topic in kRecoveryTopicCatalog) {
      var hits = 0;
      for (final kw in topic.keywords) {
        if (_containsKeywordOnBoundary(text, kw)) {
          hits++;
          if (hits >= 3) break; // Cap per-message keyword saturation per topic
        }
      }
      if (hits > 0) {
        final bonus = hits == 1 ? 1.0 : (hits == 2 ? 1.5 : 1.85);
        directScores[topic.id] =
            (directScores[topic.id] ?? 0.0) + sig.weight * bonus;
      }
    }
  }

  if (directScores.isEmpty) return const {};

  // Spread activation to NPMI-connected peer topics in the concept graph so
  // related recovery areas surface naturally alongside direct matches.
  final combined = Map<String, double>.from(directScores);
  directScores.forEach((tid, score) {
    final topic = kTopicById[tid];
    if (topic == null) return;
    for (var i = 0; i < topic.peerTopicIds.length; i++) {
      final peerId = topic.peerTopicIds[i];
      final decay = 0.38 / (1.0 + i * 0.35);
      combined[peerId] = (combined[peerId] ?? 0.0) + score * decay;
    }
  });

  return combined;
}

bool _containsKeywordOnBoundary(String text, String kw) {
  if (kw.isEmpty) return false;
  var idx = text.indexOf(kw);
  while (idx >= 0) {
    final beforeOk = idx == 0 || !_isWordChar(text.codeUnitAt(idx - 1));
    final afterIdx = idx + kw.length;
    final afterOk =
        afterIdx >= text.length || !_isWordChar(text.codeUnitAt(afterIdx));
    if (beforeOk && afterOk) return true;
    idx = text.indexOf(kw, idx + kw.length);
  }
  return false;
}

bool _isWordChar(int c) =>
    (c >= 0x61 && c <= 0x7A) ||
    (c >= 0x41 && c <= 0x5A) ||
    (c >= 0x30 && c <= 0x39);

/// SharedPreferences key for the rotation window (list of recently shown
/// prompts, oldest first).
const String _kRecentPromptsKey = 'starter_prompts_recent_v1';

/// How many recently-shown prompts stay excluded from the draw. With ~1,800+
/// prompts in the 92-topic catalog, a window of 240 ensures users can cycle
/// through dozens of sessions without repeats.
const int _kRecentWindow = 240;

/// Picks [count] starter prompts for the current time of day, blending:
/// - True-interest personalized prompts from [topicScores] (up to ~60% of the
///   hand, max 1 prompt per topic so every card explores a distinct angle)
/// - Time-of-day & evergreen discovery prompts across the 92-topic catalog
///   (remaining ~40%, or 100% when the user has no true-interest history yet)
///
/// Excludes anything shown recently (persisted across sessions) and never
/// repeats prompts already asked by the user.
List<String> pickStarterPrompts(
  SharedPreferences prefs, {
  int count = 5,
  DateTime? now,
  Random? random,
  Map<String, double>? topicScores,
  Set<String>? excludePrompts,
}) {
  final rng = random ?? Random();
  final bucket = timeBucketForNow(now);

  var recent = prefs.getStringList(_kRecentPromptsKey) ?? const <String>[];
  var recentSet = <String>{
    ...recent,
    if (excludePrompts != null) ...excludePrompts,
  };

  final picked = <String>[];
  final pickedNorm = <String>{};
  final usedTopics = <String>{};

  bool canUse(String prompt) {
    final norm = _normalizePromptKey(prompt);
    return !recentSet.contains(prompt) &&
        !recentSet.contains(norm) &&
        !pickedNorm.contains(norm);
  }

  void accept(String prompt, [String? topicId]) {
    picked.add(prompt);
    pickedNorm.add(_normalizePromptKey(prompt));
    if (topicId != null) usedTopics.add(topicId);
  }

  // 1. If we have true-interest topic scores, draw up to ceil(count * 0.6)
  //    prompts from the user's top-scoring topics & peer topics (1 per topic).
  if (topicScores != null && topicScores.isNotEmpty) {
    final targetPersonalized = (count * 3 + 2) ~/ 5; // 3 of 5 when count == 5
    final rankedTopics = topicScores.entries.toList()
      ..sort((a, b) {
        // Small jitter (±12%) among similarly-scored topics so consecutive
        // sessions rotate smoothly across the user's top interest cluster.
        final ja = a.value * (0.94 + rng.nextDouble() * 0.12);
        final jb = b.value * (0.94 + rng.nextDouble() * 0.12);
        return jb.compareTo(ja);
      });

    for (final entry in rankedTopics) {
      if (picked.length >= targetPersonalized) break;
      final topic = kTopicById[entry.key];
      if (topic == null || usedTopics.contains(topic.id)) continue;
      final available = topic.prompts.where(canUse).toList();
      if (available.isEmpty) continue;
      final chosen = available[rng.nextInt(available.length)];
      accept(chosen, topic.id);
    }
  }

  // 2. Fill remaining slots with diverse time-of-day + catalog topics (at most
  //    1 per topic first, then general time-bucketed pool).
  final discoveryTopics = kRecoveryTopicCatalog
      .where((t) => !usedTopics.contains(t.id))
      .toList()
    ..shuffle(rng);

  // Prioritize topics matching the current time-of-day affinity first.
  discoveryTopics.sort((a, b) {
    final aMatch = a.timeAffinity == bucket ? 0 : 1;
    final bMatch = b.timeAffinity == bucket ? 0 : 1;
    return aMatch.compareTo(bMatch);
  });

  // Interleave curated time-of-day prompts and 92-topic catalog prompts.
  final curatedTimePool = <String>[
    ...kStarterPrompts[bucket]!,
    ...kEvergreenPrompts,
  ].where(canUse).toList()
    ..shuffle(rng);

  var curatedIdx = 0;
  for (final topic in discoveryTopics) {
    if (picked.length >= count) break;
    // Alternate between a curated time-of-day prompt and a catalog topic prompt
    if (curatedIdx < curatedTimePool.length && picked.length.isEven) {
      final candidate = curatedTimePool[curatedIdx++];
      if (canUse(candidate)) {
        accept(candidate);
        if (picked.length >= count) break;
      }
    }
    final available = topic.prompts.where(canUse).toList();
    if (available.isNotEmpty) {
      accept(available[rng.nextInt(available.length)], topic.id);
    }
  }

  // 3. Fallback if recent window exhausted candidates
  if (picked.length < count) {
    final pool = <String>{
      ...starterPromptsForNow(now),
      ...kEvergreenPrompts,
      for (final t in kRecoveryTopicCatalog) ...t.prompts,
    }.toList();

    if (recent.length > 1) {
      recent = recent.sublist(recent.length ~/ 2);
      recentSet = recent.toSet();
    } else {
      recentSet = <String>{};
    }

    final fallback = pool.where(canUse).toList()..shuffle(rng);
    for (final p in fallback) {
      if (picked.length >= count) break;
      accept(p);
    }
  }

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
