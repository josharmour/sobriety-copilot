/// `MeditationPlayer` — a timer-driven state machine for guided sessions.
///
/// The notifier owns the [Timer]; tests drive [tick] directly and never touch
/// real time. Completion count + last-completed date persist under
/// `meditation_completed_v1`; the visual/TTS cue toggle persists under
/// `meditation_tts_v1` (TTS is opt-in — visual cues are the default).
///
/// TTS uses [AppTts] via [appTtsProvider] through a narrow [MedTts] adapter, so
/// tests can inject a fake without platform channels. `onDone` is never
/// touched (kept for chat read-aloud).
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/meditation/session.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// The narrow TTS surface the player needs: speak a one-word cue and stop
/// playback. Decoupled from [AppTts] so tests don't need platform channels.
abstract class MedTts {
  Future<void> speak(String text);
  Future<void> stop();
}

/// Adapts the app-wide [appTtsProvider] to [MedTts]. Never assigns `onDone` —
/// that callback belongs to chat read-aloud.
class _AppTtsAdapter implements MedTts {
  _AppTtsAdapter(this._app);
  final dynamic _app;

  @override
  Future<void> speak(String text) => _app.speak(text);

  @override
  Future<void> stop() => _app.stop();
}

/// Injectable provider for the player's TTS. Defaults to the app TTS; override
/// in tests with a fake.
final medTtsProvider = Provider<MedTts>(
  (ref) => _AppTtsAdapter(ref.watch(appTtsProvider)),
);

/// Live player state. `session == null` means idle; `running == false` means
/// paused (or idle). `completed` is terminal: only [MeditationPlayer.load]
/// (a fresh session) or [MeditationPlayer.stop] leave it.
class MeditationPlayerState {
  final MeditationSession? session; // null = idle
  final int cycle; // 0-based
  final int stepIndex; // 0-based
  final int secondsLeft; // seconds remaining in the current step
  final bool running; // false = paused or idle
  final bool completed; // terminal — start/resume/tick are no-ops

  const MeditationPlayerState({
    this.session,
    this.cycle = 0,
    this.stepIndex = 0,
    this.secondsLeft = 0,
    this.running = false,
    this.completed = false,
  });

  MeditationPlayerState copyWith({
    MeditationSession? session,
    int? cycle,
    int? stepIndex,
    int? secondsLeft,
    bool? running,
    bool? completed,
  }) {
    return MeditationPlayerState(
      session: session ?? this.session,
      cycle: cycle ?? this.cycle,
      stepIndex: stepIndex ?? this.stepIndex,
      secondsLeft: secondsLeft ?? this.secondsLeft,
      running: running ?? this.running,
      completed: completed ?? this.completed,
    );
  }

  /// Label of the current step, or null when idle.
  String? get currentLabel {
    final s = session;
    if (s == null || s.steps.isEmpty) return null;
    if (stepIndex < 0 || stepIndex >= s.steps.length) return null;
    return s.steps[stepIndex].label;
  }
}

/// Persistence keys.
const String kMeditationCompletedKey = 'meditation_completed_v1';
const String kMeditationTtsKey = 'meditation_tts_v1';

String _dateIso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

class MeditationPlayer extends Notifier<MeditationPlayerState> {
  Timer? _timer;

  @override
  MeditationPlayerState build() {
    // Cancel any lingering timer when the provider is disposed.
    ref.onDispose(() {
      _timer?.cancel();
      _timer = null;
    });
    return const MeditationPlayerState();
  }

  /// Whether spoken step labels are enabled (persisted, opt-in).
  bool get ttsEnabled =>
      ref.read(sharedPreferencesProvider).getBool(kMeditationTtsKey) ?? false;

  Future<void> setTtsEnabled(bool value) async {
    await ref.read(sharedPreferencesProvider).setBool(kMeditationTtsKey, value);
  }

  /// How many sessions have been completed (persisted count).
  int get completedCount {
    final raw = ref.read(sharedPreferencesProvider).getString(
          kMeditationCompletedKey,
        );
    if (raw == null || raw.isEmpty) return 0;
    try {
      return ((jsonDecode(raw) as Map<String, dynamic>)['count'] as num?)?.toInt() ??
          0;
    } catch (_) {
      return 0;
    }
  }

  /// ISO date of the last completed session, or null if never completed.
  String? get lastCompleted {
    final raw = ref.read(sharedPreferencesProvider).getString(
          kMeditationCompletedKey,
        );
    if (raw == null || raw.isEmpty) return null;
    try {
      return (jsonDecode(raw) as Map<String, dynamic>)['last'] as String?;
    } catch (_) {
      return null;
    }
  }

  /// Current step label (or null when idle).
  String? get currentLabel => state.currentLabel;

  /// Whether a session is loaded (running, paused, or completed). Lets the
  /// sheet's dispose decide if a deferred stop() is needed without modifying
  /// state from a widget lifecycle.
  bool get hasActiveSession => state.session != null;

  /// Loads a session into a paused ready state (user presses start).
  void load(MeditationSession session) {
    _timer?.cancel();
    _timer = null;
    state = MeditationPlayerState(
      session: session,
      cycle: 0,
      stepIndex: 0,
      secondsLeft: session.steps.isEmpty ? 0 : session.steps.first.seconds,
      running: false,
    );
  }

  /// Starts (or resumes from a fresh load). Speaks the first cue if enabled.
  /// No-op once the session has completed — load a fresh session instead.
  void start() {
    final s = state;
    if (s.session == null) return;
    if (s.running || s.completed) return;
    state = s.copyWith(running: true);
    if (sessionsRemaining() > 0) _speakCue(currentLabel);
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => tick());
  }

  void pause() {
    final s = state;
    if (!s.running || s.session == null) return;
    _timer?.cancel();
    _timer = null;
    state = s.copyWith(running: false);
  }

  /// Resumes from pause (does not restart the session). No-op once completed —
  /// completion is terminal and must never re-run [_finish] or re-record.
  void resume() {
    final s = state;
    if (s.session == null || s.running || s.completed) return;
    state = s.copyWith(running: true);
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => tick());
  }

  /// Fully stops the session back to idle and silences any TTS.
  Future<void> stop() async {
    _timer?.cancel();
    _timer = null;
    state = const MeditationPlayerState();
    await ref.read(medTtsProvider).stop();
  }

  /// Consumes one second of the current step. Called by the internal timer and
  /// driven directly by tests — never run against real time in tests.
  void tick() {
    final s = state;
    if (!s.running || s.session == null || s.completed) return;
    final session = s.session!;
    if (session.steps.isEmpty) {
      _finish();
      return;
    }

    if (s.secondsLeft > 1) {
      state = s.copyWith(secondsLeft: s.secondsLeft - 1);
      return;
    }

    // Current step is complete. Move to the next step, next cycle, or done.
    if (s.stepIndex + 1 < session.steps.length) {
      final next = s.stepIndex + 1;
      state = s.copyWith(
        stepIndex: next,
        secondsLeft: session.steps[next].seconds,
      );
      _speakCue(session.steps[next].label);
    } else if (s.cycle + 1 < session.cycles) {
      state = s.copyWith(
        cycle: s.cycle + 1,
        stepIndex: 0,
        secondsLeft: session.steps.first.seconds,
      );
      _speakCue(session.steps.first.label);
    } else {
      _finish();
    }
  }

  /// Number of seconds (steps × cycles) not yet consumed, for the UI.
  int sessionsRemaining() {
    final s = state;
    final session = s.session;
    if (session == null) return 0;
    return session.totalSeconds -
        (s.cycle * session.steps.fold<int>(0, (a, st) => a + st.seconds) +
            session.steps
                .take(s.stepIndex)
                .fold<int>(0, (a, st) => a + st.seconds) +
            (session.steps.isEmpty ? 0 : session.steps[s.stepIndex].seconds -
                s.secondsLeft));
  }

  void _speakCue(String? label) {
    if (!ttsEnabled || label == null || label.isEmpty) return;
    // Timer-driven; fire-and-forget. speak() internally stops any prior audio.
    unawaited(ref.read(medTtsProvider).speak(label));
  }

  void _finish() {
    _timer?.cancel();
    _timer = null;
    state = state.copyWith(running: false, secondsLeft: 0, completed: true);
    _recordCompletion();
  }

  Future<void> _recordCompletion() async {
    final now = DateTime.now();
    final today = _dateIso(now);
    final prev = completedCount;
    await ref.read(sharedPreferencesProvider).setString(
          kMeditationCompletedKey,
          jsonEncode({'count': prev + 1, 'last': today}),
        );
    // TODO(fr5): hook into the daily streak (recordCheckIn) when FR5 merges.
  }
}
