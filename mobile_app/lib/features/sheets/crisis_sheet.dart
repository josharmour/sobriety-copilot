import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';

/// Bottom-sheet that shows the AA 24-Hour Helpline as the primary resource.
/// National hotlines (988, SAMHSA) live behind a collapsed "More support
/// options" tile so the default presentation stays helpline-first while the
/// resources remain reachable (Play health/AI policy expects crisis routing).
class CrisisSheet extends StatelessWidget {
  const CrisisSheet({super.key});

  static const _aaPhone = '12126471680';

  Future<void> _call(BuildContext context, String phone) async {
    final uri = Uri(scheme: 'tel', path: phone);
    final ok = await canLaunchUrl(uri) && await launchUrl(uri);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not start a call to $phone')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.sm,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [

            Text(
              'Need to talk now?',
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w700,
                fontSize: AppTypography.title,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Call the AA 24-Hour Helpline to speak with a sober AA member, 24/7.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurface.withValues(alpha: 0.65),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            // Direct call card
            InkWell(
              onTap: () => _call(context, _aaPhone),
              borderRadius: BorderRadius.circular(12),
              child: Container(
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: theme.colorScheme.primary.withValues(alpha: 0.2),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.support_agent,
                      color: theme.colorScheme.primary,
                      size: 32,
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'AA 24-Hour Helpline',
                            style: theme.textTheme.bodyLarge?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          Text(
                            '(212) 647-1680',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.primary,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const Icon(Icons.call, color: Colors.green, size: 24),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            // Collapsed by default; national resources for review-policy
            // coverage without changing the helpline-first presentation.
            Theme(
              data: theme.copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                title: Text(
                  'More support options',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurface.withValues(alpha: 0.65),
                  ),
                ),
                children: [
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.phone_in_talk_outlined),
                    title: const Text('988 Suicide & Crisis Lifeline'),
                    subtitle: const Text('Call or text 988 — 24/7'),
                    onTap: () => _call(context, '988'),
                  ),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.support_agent_outlined),
                    title: const Text('SAMHSA National Helpline'),
                    subtitle: const Text('1-800-662-4357 — treatment referrals, 24/7'),
                    onTap: () => _call(context, '18006624357'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
