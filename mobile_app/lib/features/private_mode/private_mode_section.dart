import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/features/asr/asr_manager.dart';
import 'package:sobriety_copilot_mobile/features/private_mode/embedding_manager.dart';
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
        const _SemanticSearchTile(),
        const _VoiceDictationTile(),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

/// Optional semantic-search embedder (EmbeddingGemma). When installed,
/// Private Mode fuses keyword (BM25) with meaning-based retrieval so answers
/// cite passages even when the wording differs. Only shown once the LLM is
/// installed (it's an enhancement of that path).
class _SemanticSearchTile extends ConsumerWidget {
  const _SemanticSearchTile();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!privateModeSupported) return const SizedBox.shrink();
    final model = ref.watch(privateModelProvider);
    if (model.phase != PrivateModelPhase.installed) {
      return const SizedBox.shrink();
    }
    final embed = ref.watch(embeddingManagerProvider);
    final notifier = ref.read(embeddingManagerProvider.notifier);
    final theme = Theme.of(context);

    switch (embed.phase) {
      case EmbedPhase.notInstalled:
      case EmbedPhase.error:
        final err = embed.phase == EmbedPhase.error;
        return ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(err ? Icons.error_outline : Icons.auto_awesome_outlined,
              color: err ? AppColors.error : null),
          title: const Text('Smarter search (semantic)'),
          subtitle: Text(
            err
                ? (embed.error ?? 'Download failed')
                : 'Match by meaning, not just keywords · ~190 MB',
          ),
          trailing: TextButton(
            onPressed: notifier.download,
            child: Text(err ? 'Retry' : 'Add'),
          ),
        );
      case EmbedPhase.downloading:
        return ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(strokeWidth: 2.5),
          ),
          title: Text(
              'Downloading semantic model… ${(embed.progress * 100).toStringAsFixed(0)}%'),
          subtitle: LinearProgressIndicator(
            value: embed.progress > 0 ? embed.progress : null,
          ),
          trailing: IconButton(
            icon: const Icon(Icons.close),
            onPressed: notifier.cancel,
          ),
        );
      case EmbedPhase.installed:
        return ListTile(
          contentPadding: EdgeInsets.zero,
          dense: true,
          leading: const Icon(Icons.auto_awesome, color: AppColors.accent),
          title: const Text('Semantic search on'),
          subtitle: Text(
            'Private answers match by meaning',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          trailing: IconButton(
            icon: const Icon(Icons.delete_outline, size: 20),
            tooltip: 'Remove',
            onPressed: () async {
              await LocalChatRepository.releaseSemantic();
              await notifier.delete();
            },
          ),
        );
    }
  }
}

/// On-device voice dictation model (sherpa-onnx ASR). Optional and separate
/// from the LLM: it replaces server transcription so the mic works offline
/// and privately even without Private Mode's chat model.
class _VoiceDictationTile extends ConsumerWidget {
  const _VoiceDictationTile();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!privateModeSupported) return const SizedBox.shrink();
    final asr = ref.watch(asrManagerProvider);
    final notifier = ref.read(asrManagerProvider.notifier);

    switch (asr.state) {
      case AsrInstallState.notInstalled:
      case AsrInstallState.error:
        return ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(
            asr.state == AsrInstallState.error
                ? Icons.error_outline
                : Icons.mic_none,
            color: asr.state == AsrInstallState.error ? AppColors.error : null,
          ),
          title: const Text('On-device voice dictation'),
          subtitle: Text(
            asr.state == AsrInstallState.error
                ? (asr.error ?? 'Download failed')
                : '$kAsrDownloadMB MB · dictate offline, nothing uploaded',
          ),
          trailing: TextButton(
            onPressed: notifier.download,
            child: Text(
                asr.state == AsrInstallState.error ? 'Retry' : 'Download'),
          ),
        );
      case AsrInstallState.downloading:
        return ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(strokeWidth: 2.5),
          ),
          title: Text(
              'Downloading voice model… ${(asr.progress * 100).toStringAsFixed(0)}%'),
          subtitle: LinearProgressIndicator(
            value: asr.progress > 0 ? asr.progress : null,
          ),
        );
      case AsrInstallState.extracting:
        return const ListTile(
          contentPadding: EdgeInsets.zero,
          leading: SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(strokeWidth: 2.5),
          ),
          title: Text('Installing voice model…'),
        );
      case AsrInstallState.installed:
        return ListTile(
          contentPadding: EdgeInsets.zero,
          dense: true,
          leading: const Icon(Icons.mic, color: AppColors.accent),
          title: const Text('Voice dictation on-device'),
          subtitle: const Text('The mic transcribes locally · tap to remove'),
          trailing: IconButton(
            icon: const Icon(Icons.delete_outline, size: 20),
            tooltip: 'Remove',
            onPressed: notifier.delete,
          ),
        );
    }
  }
}

/// Async pack-installed probe, kept local to this section.
final _packInstalledProvider = FutureProvider.autoDispose<bool>((ref) async {
  return ref.watch(libraryRepositoryProvider).isPackInstalled;
});
