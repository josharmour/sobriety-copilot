import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/data/models/meeting_models.dart';
import 'package:sobriety_copilot_mobile/features/milestones/milestone_card.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/private_mode_section.dart';
import 'package:sobriety_copilot_mobile/features/milestones/sobriety_tracker.dart';
import 'package:sobriety_copilot_mobile/features/tts/neural_voices.dart';
import 'package:sobriety_copilot_mobile/features/tts/voice_manager.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Settings bottom sheet: response tone, literature categories,
/// show-thinking toggle, and read-aloud (TTS) toggle. Changes persist
/// immediately via [appConfigProvider] (mirrors the web app's
/// "Changes save automatically").
class SettingsSheet extends ConsumerWidget {
  const SettingsSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(appConfigProvider);
    final notifier = ref.read(appConfigProvider.notifier);

    return SafeArea(
      top: false,
      child: DraggableScrollableSheet(
        initialChildSize: 0.85,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) {
          return Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.sm,
                  AppSpacing.lg,
                  AppSpacing.sm,
                ),
                child: Row(
                  children: [
                    const Icon(Icons.settings_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Text(
                      'Settings',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const Spacer(),
                    IconButton(
                      icon: const Icon(Icons.check),
                      tooltip: 'Done',
                      onPressed: () => Navigator.of(context).maybePop(),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView(
                  controller: scrollController,
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    AppSpacing.md,
                    AppSpacing.lg,
                    AppSpacing.xxl,
                  ),
                  children: [
                    const _ServerStatusCard(),
                    const SizedBox(height: AppSpacing.lg),

                    const PrivateModeSection(),

                    const SectionHeader('Response tone'),
                    const SizedBox(height: AppSpacing.xs),
                    ...kTones.map(
                      (t) => _ToneTile(
                        tone: t,
                        selected: config.tone == t.id,
                        onTap: () => notifier.setTone(t.id),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),

                    const SectionHeader('Literature sources'),
                    Padding(
                      padding: const EdgeInsets.only(
                        top: AppSpacing.xs,
                        bottom: AppSpacing.sm,
                      ),
                      child: Text(
                        'By default, all literature sources are enabled. To limit '
                        'search results to conference-approved literature only, '
                        'uncheck the other sources.',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ),
                    _CategoryActions(
                      allEnabled:
                          config.enabledCategories.length == kAllCategories.length,
                      onSelectAll: () => notifier.setAllCategories(true),
                      onClear: () => notifier.setAllCategories(false),
                    ),
                    ...kAllCategories.map(
                      (id) => CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        dense: true,
                        value: config.enabledCategories.contains(id),
                        title: Text(kCategoryLabels[id] ?? id),
                        onChanged: (_) => notifier.toggleCategory(id),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),

                    const SectionHeader('Recovery tracker'),
                    Builder(builder: (context) {
                      final tracker = ref.watch(sobrietyProvider);
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.emoji_events_outlined),
                        title: Text(
                          tracker.isTracking
                              ? 'Day ${tracker.daysSober}'
                              : 'Track your sober time',
                        ),
                        subtitle: Text(
                          tracker.isTracking
                              ? 'Tap to edit · stored only on this device'
                              : 'Day count, milestones, and a home-screen widget',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => showTrackerEditor(context, ref),
                      );
                    }),
                    const SizedBox(height: AppSpacing.xl),

                    const SectionHeader('Reading & voice'),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      value: config.showThinking,
                      title: const Text('Show thinking'),
                      subtitle: const Text(
                        'Display the model\'s reasoning steps for each answer.',
                      ),
                      onChanged: (v) => notifier.setShowThinking(v),
                    ),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      value: config.studySuggestions,
                      title: const Text('Continue-your-study suggestions'),
                      subtitle: const Text(
                        'Suggest study topics from your recent questions. '
                        'Computed on this device only — nothing is uploaded.',
                      ),
                      onChanged: (v) => notifier.setStudySuggestions(v),
                    ),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      value: config.ttsEnabled,
                      title: const Text('Read answers aloud'),
                      subtitle: const Text(
                        'Enable a play button to hear answers (text-to-speech).',
                      ),
                      onChanged: (v) => notifier.setTtsEnabled(v),
                    ),
                    if (config.ttsEnabled) ...[
                      const SizedBox(height: AppSpacing.md),
                      const SectionHeader('Voice'),
                      Padding(
                        padding: const EdgeInsets.only(
                          top: AppSpacing.xs,
                          bottom: AppSpacing.sm,
                        ),
                        child: Text(
                          'Natural voices run fully on this device. Each is a '
                          'one-time download over Wi-Fi.',
                          style:
                              Theme.of(context).textTheme.bodySmall?.copyWith(
                                    color: Theme.of(context)
                                        .colorScheme
                                        .onSurfaceVariant,
                                  ),
                        ),
                      ),
                      const _VoicePicker(),
                    ],
                    const SizedBox(height: AppSpacing.lg),
                    Center(
                      child: Text(
                        'Changes save automatically',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _SheetHandle extends StatelessWidget {
  const _SheetHandle();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 40,
      height: 4,
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.onSurfaceVariant.withValues(
              alpha: 0.4,
            ),
        borderRadius: BorderRadius.circular(2),
      ),
    );
  }
}

class _ServerStatusCard extends ConsumerWidget {
  const _ServerStatusCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(healthProvider);
    final scheme = Theme.of(context).colorScheme;
    final privateActive = ref.watch(privateModeActiveProvider);

    Widget row(Color color, IconData icon, String title, String? subtitle) {
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
                if (subtitle != null && subtitle.isNotEmpty)
                  Text(
                    subtitle,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                  ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, size: 18),
            tooltip: 'Refresh',
            visualDensity: VisualDensity.compact,
            onPressed: () => ref.invalidate(healthProvider),
          ),
        ],
      );
    }

    if (privateActive) {
      return Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: row(
            AppColors.accent,
            Icons.shield_outlined,
            'Private Mode',
            'Answering on this device · nothing leaves this phone',
          ),
        ),
      );
    }

    final child = health.when(
      data: (HealthStatus h) => row(
        h.isOk ? AppColors.accent : AppColors.error,
        h.isOk ? Icons.check_circle_outline : Icons.warning_amber_outlined,
        h.isOk ? 'Connected' : 'Server degraded',
        [
          'Model: ${h.model}',
          if (h.indexedChunks != null) '${h.indexedChunks} chunks indexed',
        ].join(' · '),
      ),
      loading: () => row(
        scheme.onSurfaceVariant,
        Icons.hourglass_empty,
        'Checking connection…',
        null,
      ),
      error: (_, __) => row(
        AppColors.error,
        Icons.error_outline,
        'Connection error',
        'Check your internet connection, then tap refresh to retry.',
      ),
    );

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: child,
      ),
    );
  }
}



class _ToneTile extends StatelessWidget {
  final ToneOption tone;
  final bool selected;
  final VoidCallback onTap;

  const _ToneTile({
    required this.tone,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            border: Border.all(
              color: selected ? AppColors.accent : scheme.outlineVariant,
              width: selected ? 2 : 1,
            ),
            color: selected ? AppColors.accentSoft : null,
            borderRadius: BorderRadius.circular(AppSpacing.radius),
          ),
          child: Row(
            children: [
              Icon(
                selected
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                color: selected ? AppColors.accent : scheme.onSurfaceVariant,
                size: 20,
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tone.label,
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: selected ? AppColors.brand : null,
                          ),
                    ),
                    Text(
                      tone.desc,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: scheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _VoicePicker extends ConsumerWidget {
  const _VoicePicker();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(appConfigProvider);
    final statuses = ref.watch(voiceManagerProvider);
    final configNotifier = ref.read(appConfigProvider.notifier);
    final voices = ref.read(voiceManagerProvider.notifier);

    Future<void> downloadAndSelect(NeuralVoice v) async {
      await voices.download(v);
      // Only auto-select if the install actually succeeded.
      if (ref.read(voiceManagerProvider)[v.id]?.isInstalled == true) {
        await configNotifier.setVoiceId(v.id);
      }
    }

    return Column(
      children: [
        _VoiceTile(
          label: 'System default',
          desc: 'Built-in device voice (no download)',
          selected: config.voiceId == kSystemVoiceId,
          onTap: () => configNotifier.setVoiceId(kSystemVoiceId),
        ),
        if (!kIsWeb) ...kNeuralVoices.map((v) {
          final status = statuses[v.id] ?? VoiceStatus.notInstalled;
          final selected = config.voiceId == v.id && status.isInstalled;

          Widget? trailing;
          switch (status.state) {
            case VoiceInstallState.notInstalled:
            case VoiceInstallState.error:
              trailing = TextButton.icon(
                icon: const Icon(Icons.download, size: 18),
                label: Text('${v.sizeMB} MB'),
                onPressed: () => downloadAndSelect(v),
              );
            case VoiceInstallState.downloading:
              trailing = SizedBox(
                width: 72,
                child: LinearProgressIndicator(value: status.progress),
              );
            case VoiceInstallState.extracting:
              trailing = const SizedBox(
                width: 72,
                child: LinearProgressIndicator(),
              );
            case VoiceInstallState.installed:
              trailing = IconButton(
                icon: const Icon(Icons.delete_outline, size: 20),
                tooltip: 'Remove download',
                onPressed: () async {
                  if (config.voiceId == v.id) {
                    await configNotifier.setVoiceId(kSystemVoiceId);
                  }
                  await voices.delete(v);
                },
              );
          }

          return _VoiceTile(
            label: v.label,
            desc: status.state == VoiceInstallState.error
                ? 'Download failed — tap to retry'
                : v.desc,
            selected: selected,
            trailing: trailing,
            onTap: () {
              if (status.isInstalled) {
                configNotifier.setVoiceId(v.id);
              } else if (!status.isBusy) {
                downloadAndSelect(v);
              }
            },
          );
        }),
      ],
    );
  }
}

class _VoiceTile extends StatelessWidget {
  final String label;
  final String desc;
  final bool selected;
  final Widget? trailing;
  final VoidCallback onTap;

  const _VoiceTile({
    required this.label,
    required this.desc,
    required this.selected,
    required this.onTap,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
          decoration: BoxDecoration(
            border: Border.all(
              color: selected ? AppColors.accent : scheme.outlineVariant,
              width: selected ? 2 : 1,
            ),
            color: selected ? AppColors.accentSoft : null,
            borderRadius: BorderRadius.circular(AppSpacing.radius),
          ),
          child: Row(
            children: [
              Icon(
                selected
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                color: selected ? AppColors.accent : scheme.onSurfaceVariant,
                size: 20,
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: selected ? AppColors.brand : null,
                          ),
                    ),
                    Text(
                      desc,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: scheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
              ),
              if (trailing != null) trailing!,
            ],
          ),
        ),
      ),
    );
  }
}

class _CategoryActions extends StatelessWidget {
  final bool allEnabled;
  final VoidCallback onSelectAll;
  final VoidCallback onClear;

  const _CategoryActions({
    required this.allEnabled,
    required this.onSelectAll,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextButton(
            onPressed: allEnabled ? null : onSelectAll,
            child: const Text('Select all'),
          ),
          TextButton(
            onPressed: onClear,
            child: const Text('Clear'),
          ),
        ],
      ),
    );
  }
}
