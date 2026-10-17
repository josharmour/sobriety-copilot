import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// About / disclaimer sheet.
///
/// Surfaces what the app is, who it serves, and the important caveats:
/// it is an educational companion built on recovery literature, NOT a
/// substitute for professional help, and it is privacy-respecting.
///
/// Only the A.A. helpline (New York Intergroup) is listed as a crisis resource.
class AboutSheet extends StatelessWidget {
  const AboutSheet({super.key});

  static const String _appName = 'Sobriety Copilot';
  static const String _tagline =
      'A private, judgment-free companion grounded in recovery literature.';

  Future<void> _launch(String url) async {
    // No canLaunchUrl gate — on iOS it can report false without
    // LSApplicationQueriesSchemes and silently swallow the tap.
    final uri = Uri.parse(url);
    try {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppSheet(
      header: const SheetHeader(
        icon: Icons.explore_outlined,
        title: _appName,
        subtitle: _tagline,
      ),
      children: [
        const SectionHeader('What this is'),
        Text(
          'Sobriety Copilot helps you explore recovery literature in a '
          'warm, conversational way. Ask a question and it answers using '
          'passages drawn from the program\'s books and pamphlets, '
          'always citing where each idea comes from so you can read more.',
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: AppSpacing.lg),

        const SectionHeader('Important disclaimer'),
        const NoticeCard(
          icon: Icons.health_and_safety_outlined,
          tone: AppTone.danger,
          child: Text(
            'This app is not a substitute for professional help, medical '
            'advice, therapy, or a sponsor. It is an educational companion '
            'only. If you are in crisis or need to talk to someone now, call '
            'the A.A. helpline at (212) 647-1680 (9 am to 1 am Eastern), '
            'or 911 if you are in danger.',
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        Text(
          'Sobriety Copilot is not affiliated with, endorsed by, or an '
          'official service of Alcoholics Anonymous, Narcotics Anonymous, '
          'or any fellowship whose literature it may reference.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: AppSpacing.lg),

        const SectionHeader('Your privacy'),
        const NoticeCard(
          icon: Icons.lock_outline,
          child: Text(
            'We treat what you share as sensitive. Saved passages and '
            'your recovery tracker stay on this device. Questions you ask '
            'are answered by our own private answer service — never '
            'third-party AI providers — and are not used for advertising '
            'or tied to an account. No account is required.',
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.policy_outlined),
          title: const Text('Privacy Policy'),
          trailing: const Icon(Icons.open_in_new, size: 18),
          onTap: () => _launch('https://sobrietycopilot.com/privacy.html'),
        ),
        const SizedBox(height: AppSpacing.lg),

        const SectionHeader('Crisis resources'),
        const NoticeCard(
          icon: AppIcons.helpline,
          child: Text(
            'A.A. Helpline (New York Intergroup) — (212) 647-1680.\n'
            'Free and confidential, answered 9 am to 1 am Eastern, 7 days a week.',
          ),
        ),
        const SizedBox(height: AppSpacing.lg),

        const SectionHeader('Other paths to recovery'),
        Text(
          'While this app focuses on 12-step recovery literature, '
          'we recognize that different paths work for different people. '
          'If you are exploring other programs, resources like SMART Recovery '
          'and Refuge Recovery are also available to support you.',
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: AppSpacing.xl),

        Center(
          child: Text(
            'Made with care for anyone walking the road of recovery.\n'
            'One day at a time.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              fontStyle: FontStyle.italic,
            ),
          ),
        ),
      ],
    );
  }
}
