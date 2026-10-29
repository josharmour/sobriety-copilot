import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../daily/daily_readings.dart';
import '../daily/inventory.dart';
import '../../providers.dart';
import '../milestones/sobriety_tracker.dart';
import '../../theme/tokens.dart';

enum HomeAction {
  chat,
  checkIn,
  practice,
  meditate,
  meetings,
  graph,
  saved,
  memory,
  tracker,
  conversations,
  settings,
  evening,
}

/// Daily home and navigation over existing flows; no new storage or inferred needs.
class DayHome extends ConsumerWidget {
  final int destination;
  final ValueChanged<HomeAction> onAction;
  const DayHome({super.key, required this.destination, required this.onAction});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final now = DateTime.now();
    final tracker = ref.watch(sobrietyProvider);
    final moods = ref.watch(moodProvider);
    final checkedIn = moods.any((entry) => entry.dateIso == dateIsoOf(now));
    final readings = ref.watch(dailyReadingsProvider);
    final isLibrary = destination == 2;
    final isYou = destination == 3;
    final heading = isLibrary
        ? 'A place to explore.'
        : isYou
        ? 'Your own pace.'
        : 'A little space for today.';
    final subtitle = isLibrary
        ? 'Follow an idea, return to a passage, or take time to read.'
        : isYou
        ? 'Your history, preferences, and what you choose to remember.'
        : DateFormat('EEEE, MMMM d').format(now);

    Widget action(
      IconData icon,
      String title,
      String detail,
      HomeAction value,
    ) {
      return Card(
        margin: const EdgeInsets.only(bottom: 12),
        child: ListTile(
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 20,
            vertical: 12,
          ),
          leading: Icon(icon, color: cs.primary),
          title: Text(
            title,
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(detail),
          ),
          trailing: const Icon(Icons.arrow_forward, size: 20),
          onTap: () => onAction(value),
        ),
      );
    }

    final readingCard = Card(
      margin: EdgeInsets.zero,
      color: cs.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'A MOMENT TO READ',
              style: theme.textTheme.labelMedium?.copyWith(
                color: cs.primary,
                letterSpacing: 1.4,
              ),
            ),
            const SizedBox(height: 18),
            readings.when(
              loading: () => const Text('Loading today’s reading…'),
              error: (_, __) => const Text(
                'Today’s reading is unavailable. You can still open your daily practice.',
              ),
              data: (bundle) {
                final reading = bundle.forDate(now);
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      reading.title,
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontFamily: 'Georgia',
                        height: 1.2,
                      ),
                    ),
                    const SizedBox(height: 14),
                    Text(
                      reading.body,
                      maxLines: 5,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyLarge?.copyWith(height: 1.6),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      reading.source,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: cs.onSurfaceVariant,
                      ),
                    ),
                  ],
                );
              },
            ),
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: () => onAction(HomeAction.practice),
              icon: const Icon(AppIcons.source),
              label: const Text('Read & reflect'),
            ),
          ],
        ),
      ),
    );
    final checkInCard = Card(
      margin: EdgeInsets.zero,
      color: cs.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: DefaultTextStyle.merge(
          style: TextStyle(color: cs.onPrimaryContainer),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                checkedIn ? Icons.check_circle_outline : AppIcons.mood,
                color: cs.onPrimaryContainer,
                size: 28,
              ),
              const SizedBox(height: 18),
              Text(
                checkedIn ? 'You made space today.' : 'How are you arriving?',
                style: theme.textTheme.headlineSmall?.copyWith(
                  color: cs.onPrimaryContainer,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                checkedIn
                    ? 'Your check-in is saved on this device. You can revisit it whenever you like.'
                    : 'Name a feeling. Add a few words if you want. There’s no right answer.',
                style: const TextStyle(fontSize: 16, height: 1.5),
              ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: () => onAction(HomeAction.checkIn),
                child: Text(checkedIn ? 'Revisit check-in' : 'Check in'),
              ),
            ],
          ),
        ),
      ),
    );

    return ColoredBox(
      color: theme.scaffoldBackgroundColor,
      child: SingleChildScrollView(
        key: PageStorageKey('day-home-$destination'),
        padding: const EdgeInsets.fromLTRB(20, 28, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 960),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  isLibrary
                      ? 'LIBRARY'
                      : isYou
                      ? 'YOU'
                      : 'TODAY',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: cs.primary,
                    letterSpacing: 2,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  heading,
                  style: theme.textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  subtitle,
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: cs.onSurfaceVariant,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 24),
                if (!isLibrary && !isYou) ...[
                  action(
                    AppIcons.conversations,
                    'Talk with your copilot',
                    'Start a conversation or continue where you left off.',
                    HomeAction.chat,
                  ),
                  const SizedBox(height: 8),
                  LayoutBuilder(
                    builder: (context, constraints) =>
                        constraints.maxWidth >= 700
                        ? Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(flex: 3, child: readingCard),
                              const SizedBox(width: 20),
                              Expanded(flex: 2, child: checkInCard),
                            ],
                          )
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              checkInCard,
                              const SizedBox(height: 16),
                              readingCard,
                            ],
                          ),
                  ),
                  const SizedBox(height: 28),
                  Text('A small next step', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 12),
                  action(
                    AppIcons.meditation,
                    'Take a breathing break',
                    'Choose a guided meditation or Surf the Urge.',
                    HomeAction.meditate,
                  ),
                  action(
                    AppIcons.meetings,
                    'Find a meeting',
                    'Browse in-person and online options.',
                    HomeAction.meetings,
                  ),
                  action(
                    AppIcons.evening,
                    'Evening review',
                    'Make room to reflect on the day.',
                    HomeAction.evening,
                  ),
                ],
                if (isLibrary) ...[
                  readingCard,
                  const SizedBox(height: 20),
                  action(
                    AppIcons.graph,
                    'Explore connected ideas',
                    'Open the Knowledge Graph to follow topics through the literature.',
                    HomeAction.graph,
                  ),
                  action(
                    AppIcons.saved,
                    'Saved passages',
                    'Return to the words you chose to keep.',
                    HomeAction.saved,
                  ),
                  action(
                    AppIcons.today,
                    'Daily practice',
                    'Readings, morning practice, and evening reflection.',
                    HomeAction.practice,
                  ),
                ],
                if (isYou) ...[
                  action(
                    AppIcons.tracker,
                    tracker.isTracking
                        ? 'Day ${tracker.daysSober}'
                        : 'Your day count',
                    tracker.isTracking
                        ? 'View your milestones and tracker settings.'
                        : 'Optional. Set a start date when it feels useful.',
                    HomeAction.tracker,
                  ),
                  action(
                    AppIcons.memory,
                    'What I remember',
                    'Review and manage your optional personal memory.',
                    HomeAction.memory,
                  ),
                  action(
                    AppIcons.conversations,
                    'Conversations',
                    'Return to a previous conversation.',
                    HomeAction.conversations,
                  ),
                  action(
                    AppIcons.mood,
                    'Check-in & journal',
                    'View today’s entry or open your check-in history.',
                    HomeAction.checkIn,
                  ),
                  action(
                    AppIcons.settings,
                    'Settings',
                    'Appearance, privacy, voice, and preferences.',
                    HomeAction.settings,
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
