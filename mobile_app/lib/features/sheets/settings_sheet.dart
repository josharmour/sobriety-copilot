import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/data/models/meeting_models.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Settings bottom sheet: baseUrl, response tone, literature categories,
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
              const _SheetHandle(),
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

                    const SectionHeader('Server'),
                    _BaseUrlField(
                      initialValue: config.baseUrl,
                      onSubmitted: (value) => notifier.setBaseUrl(value),
                    ),
                    const SizedBox(height: AppSpacing.xl),

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
                      value: config.ttsEnabled,
                      title: const Text('Read answers aloud'),
                      subtitle: const Text(
                        'Enable a play button to hear answers (text-to-speech).',
                      ),
                      onChanged: (v) => notifier.setTtsEnabled(v),
                    ),
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
        'Is the server running? Check the base URL below.',
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

class _BaseUrlField extends StatefulWidget {
  final String initialValue;
  final ValueChanged<String> onSubmitted;

  const _BaseUrlField({
    required this.initialValue,
    required this.onSubmitted,
  });

  @override
  State<_BaseUrlField> createState() => _BaseUrlFieldState();
}

class _BaseUrlFieldState extends State<_BaseUrlField> {
  late final TextEditingController _controller;
  late final FocusNode _focusNode;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialValue);
    _focusNode = FocusNode();
    _focusNode.addListener(() {
      if (!_focusNode.hasFocus) {
        _commit();
      }
    });
  }

  void _commit() {
    final value = _controller.text.trim();
    if (value.isNotEmpty && value != widget.initialValue) {
      widget.onSubmitted(value);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _controller,
      focusNode: _focusNode,
      keyboardType: TextInputType.url,
      textInputAction: TextInputAction.done,
      autocorrect: false,
      decoration: InputDecoration(
        labelText: 'Server base URL',
        hintText: kDefaultBaseUrl,
        prefixIcon: const Icon(Icons.link),
        border: const OutlineInputBorder(),
      ),
      onSubmitted: (_) => _commit(),
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
