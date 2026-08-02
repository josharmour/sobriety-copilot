// Unit tests for the FR9 meditation model, library, and player state machine.
//
// The player is timer-driven: the internal Timer.periodic calls `tick()`, and
// tests drive `tick()` directly against a ProviderContainer — never real time.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:sobriety_copilot_mobile/features/meditation/player.dart';
import 'package:sobriety_copilot_mobile/features/meditation/session.dart';
import 'package:sobriety_copilot_mobile/providers.dart';

/// Fake [MedTts] that records cues and stop calls without any platform channel.
class _FakeMedTts implements MedTts {
  final List<String> spoken = [];
  int stopCalls = 0;

  @override
  Future<void> speak(String text) async => spoken.add(text);

  @override
  Future<void> stop() async => stopCalls++;
}

const _breath478 = MeditationSession(
  id: 'breath_478',
  title: '4-7-8 Breathing',
  description: 'Calm the nervous system.',
  steps: [MedStep('Inhale', 4), MedStep('Hold', 7), MedStep('Exhale', 8)],
  cycles: 1,
);

Future<(ProviderContainer, _FakeMedTts, MeditationPlayer)> _makePlayer({
  bool tts = false,
}) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final prefs = await SharedPreferences.getInstance();
  if (tts) await prefs.setBool(kMeditationTtsKey, true);
  final fakeTts = _FakeMedTts();
  final container = ProviderContainer(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      medTtsProvider.overrideWithValue(fakeTts),
    ],
  );
  addTearDown(container.dispose);
  final notifier = container.read(meditationPlayerProvider.notifier);
  return (container, fakeTts, notifier);
}

/// Advances the session `n` seconds by driving tick().
void _tickN(MeditationPlayer p, int n) {
  for (var i = 0; i < n; i++) {
    p.tick();
  }
}

void main() {
  group('MeditationSession.totalSeconds', () {
    test('computes total duration across steps and cycles', () {
      const s = MeditationSession(
        id: 'breath_478',
        title: '4-7-8 Breathing',
        description: 'Calm the nervous system.',
        steps: [
          MedStep('Inhale', 4),
          MedStep('Hold', 7),
          MedStep('Exhale', 8),
        ],
        cycles: 4,
      );
      expect(s.totalSeconds, 4 * (4 + 7 + 8));
    });

    test('single cycle defaults to 1', () {
      const s = MeditationSession(
        id: 'x',
        title: 'X',
        description: 'Y',
        steps: [MedStep('A', 3), MedStep('B', 2)],
      );
      expect(s.cycles, 1);
      expect(s.totalSeconds, 5);
    });
  });

  group('kMeditations curated library', () {
    test('contains the four approved sessions', () {
      expect(kMeditations.map((s) => s.id), [
        'surf_urge',
        'breath_478',
        'box',
        'body_scan',
      ]);
    });

    test('surf the urge is first (top placement for craving moments)', () {
      expect(kMeditations.first.id, 'surf_urge');
    });

    test('ids are unique', () {
      final ids = kMeditations.map((s) => s.id).toSet();
      expect(ids.length, kMeditations.length);
    });

    test('every session has positive duration and at least one step', () {
      for (final s in kMeditations) {
        expect(s.totalSeconds, greaterThan(0));
        expect(s.steps, isNotEmpty);
      }
    });
  });

  group('MeditationPlayer state machine', () {
    test('load prepares a paused session at the first step', () async {
      final (_, _, p) = await _makePlayer();
      p.load(_breath478);
      final s = p.state;
      expect(s.session?.id, 'breath_478');
      expect(s.cycle, 0);
      expect(s.stepIndex, 0);
      expect(s.secondsLeft, 4);
      expect(s.running, isFalse);
    });

    test('start() begins running and speaks no TTS when disabled', () async {
      final (_, tts, p) = await _makePlayer(tts: false);
      p.load(_breath478);
      p.start();
      expect(p.state.running, isTrue);
      expect(tts.spoken, isEmpty);
    });

    test('advances seconds within a step', () async {
      final (_, _, p) = await _makePlayer();
      p.load(_breath478);
      p.start();
      p.tick();
      expect(p.state.secondsLeft, 3);
      expect(p.state.stepIndex, 0);
    });

    test('advances to the next step when a step completes', () async {
      final (_, _, p) = await _makePlayer();
      p.load(_breath478);
      p.start();
      _tickN(p, 4); // consume the 4s Inhale
      expect(p.state.stepIndex, 1);
      expect(p.state.secondsLeft, 7); // Hold
      expect(p.currentLabel, 'Hold');
    });

    test('steps spoken only when tts enabled', () async {
      final (_, tts, p) = await _makePlayer(tts: true);
      p.load(_breath478);
      p.start();
      expect(tts.spoken, ['Inhale']); // first cue on start
      _tickN(p, 4);
      expect(tts.spoken, ['Inhale', 'Hold']); // cue on step change
    });

    test('completes the session, stops, and persists count/date', () async {
      final (container, _, p) = await _makePlayer();
      p.load(_breath478);
      p.start();
      expect(p.state.running, isTrue);
      _tickN(p, 4 + 7 + 8); // full 4-7-8 single cycle
      expect(p.state.running, isFalse);
      expect(p.state.stepIndex, 2);
      expect(p.completedCount, 1);
      expect(p.lastCompleted, isNotNull);
      // Persisted through the same prefs instance.
      expect(
        container.read(sharedPreferencesProvider).getString(
              kMeditationCompletedKey,
            ),
        contains('count'),
      );
    });

    test('pause stops the clock; resume continues from same position',
        () async {
      final (_, _, p) = await _makePlayer();
      p.load(_breath478);
      p.start();
      _tickN(p, 2);
      p.pause();
      expect(p.state.running, isFalse);
      expect(p.state.secondsLeft, 2);
      // Paused: tick() is a no-op (the timer is cancelled; test mimics a rogue
      // call to guard against accidental ticking while paused).
      p.tick();
      expect(p.state.secondsLeft, 2);
      p.resume();
      expect(p.state.running, isTrue);
      p.tick();
      expect(p.state.secondsLeft, 1);
    });

    test('stop() silences TTS and returns to idle', () async {
      final (_, tts, p) = await _makePlayer();
      p.load(_breath478);
      p.start();
      await p.stop();
      expect(p.state.session, isNull);
      expect(p.state.running, isFalse);
      expect(tts.stopCalls, greaterThan(0));
    });

    test('cycles repeat until all cycles complete', () async {
      const twoCycle = MeditationSession(
        id: 'box',
        title: 'Box Breathing',
        description: 'Steady, even breath.',
        steps: [MedStep('Inhale', 2), MedStep('Exhale', 2)],
        cycles: 2,
      );
      final (_, _, p) = await _makePlayer();
      p.load(twoCycle);
      p.start();
      _tickN(p, 2);
      expect(p.state.stepIndex, 1); // Exhale (cycle 0)
      _tickN(p, 2);
      expect(p.state.cycle, 1); // back to Inhale in cycle 1
      expect(p.state.stepIndex, 0);
      _tickN(p, 4); // finish cycle 1
      expect(p.state.running, isFalse);
      expect(p.completedCount, 1);
    });
  });

  group('MeditationPlayer TTS toggle', () {
    test('toggle persists to shared preferences', () async {
      final (container, _, p) = await _makePlayer();
      expect(p.ttsEnabled, isFalse);
      await p.setTtsEnabled(true);
      expect(p.ttsEnabled, isTrue);
      final prefs = container.read(sharedPreferencesProvider);
      expect(prefs.getBool(kMeditationTtsKey), isTrue);
    });
  });
}
