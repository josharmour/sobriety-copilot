import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';

/// Info on alternative / supplementary recovery programs, mirroring the web
/// app's meeting launchers. Each entry opens an external meeting finder via
/// [url_launcher].
class AltRecoverySheet extends StatelessWidget {
  const AltRecoverySheet({super.key});

  static const List<_AltProgram> _programs = [
    _AltProgram(
      name: 'AA online meetings',
      detail: 'aa-intergroup.org · 24/7 worldwide',
      url: 'https://aa-intergroup.org/meetings/',
      icon: Icons.public,
    ),
    _AltProgram(
      name: 'NA meetings',
      detail: 'Narcotics Anonymous · Worldwide',
      url: 'https://www.na.org/meetingsearch/',
      icon: Icons.groups_outlined,
    ),
    _AltProgram(
      name: 'SMART Recovery',
      detail: 'Science-based, in-person and online',
      url: 'https://meetings.smartrecovery.org/meetings/',
      icon: Icons.psychology_outlined,
    ),
    _AltProgram(
      name: 'Refuge Recovery',
      detail: 'Buddhist-inspired · In-person and online',
      url: 'https://refugerecovery.org/meetings',
      icon: Icons.self_improvement_outlined,
    ),
  ];

  Future<void> _open(BuildContext context, String url) async {
    final uri = Uri.parse(url);
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open $url')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.md,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [

            Row(
              children: [
                const Icon(Icons.diversity_3_outlined, color: AppColors.accent),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    'Find a meeting',
                    style: theme.textTheme.titleLarge,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Different paths work for different people. Explore fellowships '
              'and programs that fit you.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.textTheme.bodySmall?.color,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            ..._programs.map(
              (p) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: _ProgramTile(
                  program: p,
                  onTap: () => _open(context, p.url),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            Center(
              child: Text(
                'Showing up is half the work.',
                style: theme.textTheme.bodySmall,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AltProgram {
  final String name;
  final String detail;
  final String url;
  final IconData icon;
  const _AltProgram({
    required this.name,
    required this.detail,
    required this.url,
    required this.icon,
  });
}

class _ProgramTile extends StatelessWidget {
  final _AltProgram program;
  final VoidCallback onTap;
  const _ProgramTile({required this.program, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: AppColors.accentSoft.withValues(
        alpha: theme.brightness == Brightness.dark ? 0.12 : 1.0,
      ),
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              Icon(program.icon, color: AppColors.accent),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      program.name,
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      program.detail,
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.open_in_new, size: 18),
            ],
          ),
        ),
      ),
    );
  }
}
