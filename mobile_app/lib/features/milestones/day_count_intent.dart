/// Decides when the local-only sobriety day count should be shared with the
/// assistant for a given message.
///
/// The day count is ambient personal context. If we hand it to the model on
/// every turn, the model recites it every turn ("You're on day 92 — keep
/// going!"), which users find repetitive and off-topic. So we only attach it
/// when the person's message is genuinely about their *own* time in recovery.
///
/// Deliberately narrow: a bare "day", "days", "clean", "sober", or "sobriety"
/// must NOT trigger it — those words appear in ordinary questions ("how do I
/// get through the day?", "I want to clean up my life", "how do I stay
/// sober at parties?") that have nothing to do with the person's day count.
library;

/// Whether [message] is asking about — or stating — the user's own time in
/// recovery (day count, milestone, anniversary). Case-insensitive.
bool queryWantsDayCount(String message) {
  final m = message.toLowerCase();

  // 1. Direct questions about where they stand.
  final asksStanding = RegExp(
    r"how\s+long\s+(have\s+i|since\s+i|.*\b(sober|clean|in\s+recovery))"
    r"|how\s+many\s+days"
    r"|how\s+am\s+i\s+doing"
    r"|how\s+far\s+along"
    r"|how'?s\s+my\s+(sobriety|sober|clean|recovery|progress|streak|count|number|time)"
    r"|what('?s|\s+is)\s+my\s+(day\s+count|count|number|streak)",
  ).hasMatch(m);
  if (asksStanding) return true;

  // 2. Explicit references to their own count / milestone / date.
  final refsCount = RegExp(
    r"\bday\s+count\b"
    r"|\bdays?\s+(sober|clean)\b"
    r"|\bmy\s+(sobriety|sober\s+date|clean\s+date|clean\s+time|recovery|progress|streak|number|count)\b"
    r"|\b(sober|sobriety|clean|recovery)\s+(birthday|anniversary)\b"
    r"|\b(milestone|milestones|anniversary)\b",
  ).hasMatch(m);
  if (refsCount) return true;

  // 3. A first-person claim of a specific amount of time
  //    ("I have 90 days", "I'm at 6 months", "I just hit 30 days"). Anchored
  //    to a claim verb — a bare "I" would catch "I want 2 days off work".
  final statesAmount = RegExp(
    r"\b(i'?m|i\s+am|i'?ve|i\s+have|i\s+just|i\s+hit|i\s+reached|i\s+got|i\s+made|i\s+celebrat)\b"
    r"[^.?!]{0,24}\b\d+\s*(day|days|week|weeks|month|months|year|years)\b",
  ).hasMatch(m);
  return statesAmount;
}
