/// Data model for a guided meditation / breathing session.
///
/// Sessions are entirely on-device: no audio assets — the player drives a
/// timed state machine with visual + (opt-in) TTS cues from [steps].
library;

/// One timed step of a session (e.g. "Inhale for 4s").
class MedStep {
  final String label;
  final int seconds;

  const MedStep(this.label, this.seconds);
}

/// A curated, guided session: an ordered list of [steps] repeated [cycles]
/// times. Wellness framing only — never positioned as medical treatment.
class MeditationSession {
  final String id;
  final String title;
  final String description;
  final List<MedStep> steps;
  final int cycles;

  const MeditationSession({
    required this.id,
    required this.title,
    required this.description,
    required this.steps,
    this.cycles = 1,
  });

  /// Total wall-clock duration across all cycles, in seconds.
  int get totalSeconds =>
      cycles * steps.fold<int>(0, (a, s) => a + s.seconds);
}

/// Curated on-device library. Description copy is approved as-is (wellness
/// only — "calms the nervous system" is the ceiling). "Surf the Urge" is
/// listed first: it is the app's only in-the-moment craving tool.
const List<MeditationSession> kMeditations = [
  MeditationSession(
    id: 'surf_urge',
    title: 'Surf the Urge',
    description: 'Cravings pass like waves. Ride it out.',
    steps: [MedStep('Breathe', 6), MedStep('Notice', 6), MedStep('Rest', 6)],
    cycles: 5,
  ),
  MeditationSession(
    id: 'breath_478',
    title: '4-7-8 Breathing',
    description: 'Calm the nervous system.',
    steps: [MedStep('Inhale', 4), MedStep('Hold', 7), MedStep('Exhale', 8)],
    cycles: 4,
  ),
  MeditationSession(
    id: 'box',
    title: 'Box Breathing',
    description: 'Steady, even breath.',
    steps: [
      MedStep('Inhale', 4),
      MedStep('Hold', 4),
      MedStep('Exhale', 4),
      MedStep('Hold', 4),
    ],
    cycles: 4,
  ),
  MeditationSession(
    id: 'body_scan',
    title: 'Mini Body Scan',
    description: 'Notice and release tension.',
    steps: [MedStep('Settle', 10), MedStep('Soften', 10), MedStep('Release', 10)],
    cycles: 2,
  ),
];
