import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/private_mode/local_chat_repository.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/model_manager.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Settings section for Private Mode: model download lifecycle + the
/// on-device toggle. Only rendered on supported surfaces (Android).
class PrivateModeSection extends ConsumerWidget {
  const PrivateModeSection({super.key});

  Future<void> _confirmDownload(BuildContext context, WidgetRef ref) async {
    final proceed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Download the on-device model?'),
        content: const Text(
          '$kPrivateModelName is a 2.6 GB one-time download — Wi-Fi '
          'strongly recommended. Once installed, Private Mode answers '
          'entirely on this phone: your questions never leave the device.\n\n'
          'Works best on recent phones with 8 GB of memory or more.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Not now'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Download'),
          ),
        ],
      ),
    );
    if (proceed == true) {
      ref.read(privateModelProvider.notifier).download();
    }
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
    final proceed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove the on-device model?'),
        content: const Text(
          'Frees 2.6 GB. Chat falls back to the server until you download '
          'it again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (proceed == true) {
      await ref.read(appConfigProvider.notifier).setPrivateMode(false);
      await LocalChatRepository.releaseModel();
      await ref.read(privateModelProvider.notifier).delete();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!privateModeSupported) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final model = ref.watch(privateModelProvider);
    final config = ref.watch(appConfigProvider);
    final packInstalledAsync = ref.watch(_packInstalledProvider);
    final packInstalled = packInstalledAsync.value ?? false;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader('Private Mode'),
        Padding(
          padding: const EdgeInsets.only(
            top: AppSpacing.xs,
            bottom: AppSpacing.sm,
          ),
          child: Text(
            'Answer with a model that runs entirely on this phone — '
            'questions and answers never leave the device. Uses the offline '
            'Recovery Library for citations.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        switch (model.phase) {
          PrivateModelPhase.notInstalled => ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.download_outlined),
              title: const Text('Download $kPrivateModelName'),
              subtitle: const Text('2.6 GB · one time · Wi-Fi recommended'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _confirmDownload(context, ref),
            ),
          PrivateModelPhase.downloading => ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              title: Text(
                'Downloading… ${(model.progress * 100).toStringAsFixed(0)}%',
              ),
              subtitle: LinearProgressIndicator(
                value: model.progress > 0 ? model.progress : null,
              ),
              trailing: IconButton(
                icon: const Icon(Icons.close),
                tooltip: 'Cancel',
                onPressed: () =>
                    ref.read(privateModelProvider.notifier).cancelDownload(),
              ),
            ),
          PrivateModelPhase.error => ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.error_outline, color: AppColors.error),
              title: const Text('Download failed'),
              subtitle: Text(
                model.error ?? 'Unknown error',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              trailing: TextButton(
                onPressed: () => _confirmDownload(context, ref),
                child: const Text('Retry'),
              ),
            ),
          PrivateModelPhase.installed => Column(
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: config.privateMode,
                  title: const Text('Answer on this device'),
                  subtitle: Text(
                    config.privateMode
                        ? '$kPrivateModelName · nothing leaves this phone'
                        : 'Model ready — flip to go private',
                  ),
                  onChanged: (v) async {
                    await ref
                        .read(appConfigProvider.notifier)
                        .setPrivateMode(v);
                    if (!v) await LocalChatRepository.releaseModel();
                  },
                ),
                if (config.privateMode && !packInstalled)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: Row(
                      children: [
                        const Icon(Icons.info_outline,
                            size: 16, color: AppColors.gold),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Text(
                            'Install the offline Recovery Library (menu → '
                            'Recovery library) so private answers can cite '
                            'the literature.',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  leading: const Icon(Icons.delete_outline, size: 20),
                  title: const Text('Remove model (frees 2.6 GB)'),
                  onTap: () => _confirmDelete(context, ref),
                ),
              ],
            ),
        },
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

/// Async pack-installed probe, kept local to this section.
final _packInstalledProvider = FutureProvider.autoDispose<bool>((ref) async {
  return ref.watch(libraryRepositoryProvider).isPackInstalled;
});
