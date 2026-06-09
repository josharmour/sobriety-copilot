import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// About / disclaimer sheet.
///
/// Surfaces what the app is, who it serves, and the important caveats:
/// it is an educational companion built on recovery literature, NOT a
/// substitute for professional help, and it is privacy-respecting.
class AboutSheet extends StatelessWidget {
  const AboutSheet({super.key});

  static const String _appName = 'Sobriety Copilot';
  static const String _tagline =
      'A private, judgment-free companion grounded in recovery literature.';

  Future<void> _launch(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    return SafeArea(
      top: false,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.sm,
          AppSpacing.lg,
          AppSpacing.xl,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // Header
            Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppColors.accentSoft,
                    borderRadius: BorderRadius.circular(AppSpacing.radius),
                  ),
                  child: const Icon(
                    Icons.explore_outlined,
                    color: AppColors.brand,
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _appName,
                        style: theme.textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        _tagline,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: cs.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xl),

            const SectionHeader('What this is'),
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Sobriety Copilot helps you explore recovery literature in a '
              'warm, conversational way. Ask a question and it answers using '
              'passages drawn from the program’s books and pamphlets, '
              'always citing where each idea comes from so you can read more.',
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.xl),

            const SectionHeader('Important disclaimer'),
            const SizedBox(height: AppSpacing.sm),
            _NoticeCard(
              icon: Icons.health_and_safety_outlined,
              color: AppColors.error,
              child: Text(
                'This app is not a substitute for professional help, medical '
                'advice, therapy, or a sponsor. It is an educational companion '
                'only. If you are in crisis or may be in danger, call 911, or '
                'reach SAMHSA’s free 24/7 helpline at 1-800-662-4357.',
                style: theme.textTheme.bodyMedium,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              'Sobriety Copilot is not affiliated with, endorsed by, or an '
              'official service of Alcoholics Anonymous, Narcotics Anonymous, '
              'or any fellowship whose literature it may reference.',
              style: theme.textTheme.bodySmall?.copyWith(
                color: cs.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: AppSpacing.xl),

            const SectionHeader('Your privacy'),
            const SizedBox(height: AppSpacing.sm),
            _NoticeCard(
              icon: Icons.lock_outline,
              color: AppColors.accent,
              child: Text(
                'We treat what you share as sensitive. Your conversations and '
                'saved passages stay on this device. No account is required, '
                'and nothing is shared with anyone but the answer service used '
                'to respond to your questions.',
                style: theme.textTheme.bodyMedium,
              ),
            ),
            const SizedBox(height: AppSpacing.xl),

            const SectionHeader('Crisis resources'),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                AppChip(
                  label: 'SAMHSA 1-800-662-4357',
                  icon: Icons.call_outlined,
                  onTap: () => _launch('tel:18006624357'),
                ),
                AppChip(
                  label: '988 Lifeline',
                  icon: Icons.call_outlined,
                  onTap: () => _launch('tel:988'),
                ),
                AppChip(
                  label: '911',
                  icon: Icons.emergency_outlined,
                  onTap: () => _launch('tel:911'),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xl),

            Center(
              child: Text(
                'Made with care for anyone walking the road of recovery.\n'
                'One day at a time.',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: cs.onSurfaceVariant,
                  fontStyle: FontStyle.italic,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Small highlighted card used for the disclaimer / privacy notices.
class _NoticeCard extends StatelessWidget {
  final IconData icon;
  final Color color;
  final Widget child;

  const _NoticeCard({
    required this.icon,
    required this.color,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: AppSpacing.md),
          Expanded(child: child),
        ],
      ),
    );
  }
}
