// Unit tests for the FR9 meditation model + curated library.

import 'package:flutter_test/flutter_test.dart';
import 'package:sobriety_copilot_mobile/features/meditation/session.dart';

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
}
