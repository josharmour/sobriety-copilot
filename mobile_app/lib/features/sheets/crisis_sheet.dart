import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// Bottom-sheet that shows the AA 24-Hour Helpline as the primary resource.
/// National hotlines (988, SAMHSA) live behind a collapsed "More support
/// options" tile so the default presentation stays helpline-first while the
/// resources remain reachable (Play health/AI policy expects crisis routing).
class CrisisSheet extends StatelessWidget {
  const CrisisSheet({super.key});

  /// Opens the sheet sized to its content (it is short, and reachable from
  /// several places — keep every entry point identical).
  static Future<void> show(BuildContext context) =>
      showAppSheet<void>(context, const CrisisSheet(), fitContent: true);

  static const _aaPhone = '12126471680';

  Future<void> _call(BuildContext context, String phone) async {
    // No canLaunchUrl gate: on iOS it reports false for tel: unless the
    // scheme is declared in LSApplicationQueriesSchemes, silently breaking
    // the call button. launchUrl itself is the reliable check.
    final uri = Uri(scheme: 'tel', path: phone);
    var ok = false;
    try {
      ok = await launchUrl(uri);
    } catch (_) {}
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not start a call to $phone')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return AppSheet(
      header: const SheetHeader(
        icon: AppIcons.crisis,
        title: 'Need to talk now?',
        subtitle:
            'Call the AA 24-Hour Helpline to speak with a sober AA member, 24/7.',
      ),
      children: [
        ActionCard(
          icon: AppIcons.helpline,
          title: 'AA 24-Hour Helpline',
          subtitle: '(212) 647-1680',
          trailing: Icon(Icons.call, color: cs.success),
          onTap: () => _call(context, _aaPhone),
        ),
        const SizedBox(height: AppSpacing.sm),
        // Collapsed by default; national resources for review-policy
        // coverage without changing the helpline-first presentation.
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: EdgeInsets.zero,
          title: Text(
            'More support options',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: cs.onSurfaceVariant,
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
      ],
    );
  }
}
