import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';

/// Static crisis-resource sheet. Mirrors the web app's "If you need someone
/// right now" panel: AA helpline, SAMHSA, 988, and 911 (urgent), each
/// tap-to-call via `tel:` using url_launcher.
class CrisisSheet extends StatelessWidget {
  const CrisisSheet({super.key});

  static const List<_CrisisResource> _resources = [
    _CrisisResource(
      name: 'AA 24-Hour Helpline',
      detail: '212-647-1680 · Talk to a sober AA member, 24/7',
      phone: '12126471680',
      icon: Icons.support_agent,
    ),
    _CrisisResource(
      name: 'SAMHSA Helpline',
      detail: '1-800-662-HELP (4357) · Substance use, 24/7',
      phone: '18006624357',
      icon: Icons.medical_services_outlined,
    ),
    _CrisisResource(
      name: '988 Suicide & Crisis Lifeline',
      detail: 'Call or text 988 · Mental health, 24/7',
      phone: '988',
      icon: Icons.favorite_outline,
    ),
    _CrisisResource(
      name: 'Emergency',
      detail: "911 · If there's immediate danger",
      phone: '911',
      icon: Icons.local_hospital_outlined,
      urgent: true,
    ),
  ];

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
            Center(
              child: Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: AppSpacing.lg),
                decoration: BoxDecoration(
                  color: theme.dividerColor,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Text(
              'If you need someone right now',
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w700,
                fontSize: AppTypography.title,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'These lines are free, confidential, and open around the clock.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.textTheme.bodySmall?.color,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            for (final r in _resources) ...[
              _CrisisTile(resource: r, onTap: () => _call(context, r.phone)),
              const SizedBox(height: AppSpacing.sm),
            ],
            const SizedBox(height: AppSpacing.sm),
            Center(
              child: Text(
                "You're not alone. Reaching out is a strong step.",
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
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

class _CrisisResource {
  final String name;
  final String detail;
  final String phone;
  final IconData icon;
  final bool urgent;
  const _CrisisResource({
    required this.name,
    required this.detail,
    required this.phone,
    required this.icon,
    this.urgent = false,
  });
}

class _CrisisTile extends StatelessWidget {
  final _CrisisResource resource;
  final VoidCallback onTap;
  const _CrisisTile({required this.resource, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final iconColor = resource.urgent ? AppColors.error : AppColors.accent;
    final borderColor =
        resource.urgent ? AppColors.error : theme.dividerColor;
    return Material(
      color: theme.cardColor,
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppSpacing.radius),
            border: Border.all(color: borderColor),
          ),
          child: Row(
            children: [
              Icon(resource.icon, color: iconColor),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      resource.name,
                      style: theme.textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      resource.detail,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.textTheme.bodySmall?.color,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Icon(
                Icons.call,
                size: 18,
                color: theme.iconTheme.color?.withValues(alpha: 0.5),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
