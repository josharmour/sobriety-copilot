import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

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
    return AppSheet(
      header: const SheetHeader(
        icon: AppIcons.altPaths,
        title: 'Other recovery paths',
        subtitle: 'Different paths work for different people. Explore '
            'fellowships and programs that fit you.',
      ),
      children: [
        for (final p in _programs) ...[
          ActionCard(
            icon: p.icon,
            title: p.name,
            subtitle: p.detail,
            trailing: Icon(
              Icons.open_in_new,
              size: 18,
              color: theme.colorScheme.onSurfaceVariant,
            ),
            onTap: () => _open(context, p.url),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        const SizedBox(height: AppSpacing.sm),
        Center(
          child: Text(
            'Showing up is half the work.',
            style: theme.textTheme.bodySmall,
          ),
        ),
      ],
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
