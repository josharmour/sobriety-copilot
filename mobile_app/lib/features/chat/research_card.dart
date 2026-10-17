/// How a research-mode answer was made: the steps (live while researching),
/// then a compact summary with the check of its quotes and page citations.
library;

import 'package:flutter/material.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

class ResearchCard extends StatefulWidget {
  final ChatMessage message;
  const ResearchCard({super.key, required this.message});

  @override
  State<ResearchCard> createState() => _ResearchCardState();
}

class _ResearchCardState extends State<ResearchCard> {
  bool? _expanded; // null = follow the default (open while researching)

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final m = widget.message;
    // Working until the answer's first words arrive (the model thinks before it writes).
    final working = m.isStreaming && m.text.trim().isEmpty;
    final writing = m.researchPhase == 'writing';
    final expanded = _expanded ?? (working && !writing);
    final steps = m.researchSteps;
    final reads = steps.where((s) => s.tool == 'read_section' && s.status == 'done').length;
    final analyzed = steps.where((s) => s.tool == 'analyze_sections' && s.status == 'done').length;
    final searches = steps.where((s) => s.tool == 'search' || s.tool == 'find_text').length;
    final summary = working
        ? (writing ? 'Writing the answer…' : steps.isEmpty ? 'Planning the research…' : steps.last.label)
        : [
            if (reads > 0) 'read $reads section${reads == 1 ? '' : 's'}',
            if (analyzed > 0) '$analyzed close reading${analyzed == 1 ? '' : 's'}',
            if (searches > 0) '$searches search${searches == 1 ? '' : 'es'}',
          ].join(' · ');

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
          onTap: steps.isEmpty ? null : () => setState(() => _expanded = !expanded),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: Row(children: [
              if (working)
                const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
              else
                Icon(Icons.travel_explore, size: 16, color: theme.colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  working ? summary : 'Researched${summary.isEmpty ? '' : ': $summary'}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              if (m.researchCheck != null) ...[
                const SizedBox(width: 6),
                _CheckBadge(check: m.researchCheck!),
              ],
              if (steps.isNotEmpty) Icon(expanded ? Icons.expand_less : Icons.expand_more, size: 18),
            ]),
          ),
        ),
        if (expanded && steps.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final s in steps) _stepRow(theme, s),
              if (m.researchCheck != null && m.researchCheck!.unverified.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text('Not found word-for-word in the text:', style: theme.textTheme.labelSmall),
                for (final q in m.researchCheck!.unverified)
                  Text('“$q”', style: theme.textTheme.labelSmall?.copyWith(fontStyle: FontStyle.italic)),
              ],
            ]),
          ),
      ]),
    );
  }

  Widget _stepRow(ThemeData theme, ResearchStep s) {
    final icon = switch (s.status) {
      'done' => Icon(Icons.check_circle, size: 14, color: theme.colorScheme.primary),
      'error' => Icon(Icons.error_outline, size: 14, color: theme.colorScheme.error),
      _ => const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 1.6)),
    };
    final extra = s.status == 'running' && s.done != null && s.total != null ? ' (${s.done}/${s.total})' : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 2), child: icon),
        const SizedBox(width: 8),
        Expanded(
          child: Text.rich(
            TextSpan(children: [
              TextSpan(text: s.label + extra),
              if (s.detail != null && s.detail!.isNotEmpty)
                TextSpan(text: ' — ${s.detail}', style: TextStyle(color: theme.colorScheme.onSurfaceVariant)),
            ]),
            style: theme.textTheme.bodySmall,
          ),
        ),
      ]),
    );
  }
}

class _CheckBadge extends StatelessWidget {
  final ResearchCheck check;
  const _CheckBadge({required this.check});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ok = check.allVerified;
    final color = ok ? const Color(0xFF2E7D57) : theme.colorScheme.tertiary;
    final parts = [
      if (check.quotes > 0) '${check.quotesVerified}/${check.quotes} quotes',
      if (check.pages > 0) '${check.pagesVerified}/${check.pages} pages',
    ];
    return Tooltip(
      message: 'Quotes and page numbers in this answer, checked against the text of the books',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withValues(alpha: 0.5)),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(ok ? Icons.verified : Icons.info_outline, size: 12, color: color),
          const SizedBox(width: 3),
          Text('${parts.join(' · ')} checked', style: theme.textTheme.labelSmall?.copyWith(color: color, fontWeight: FontWeight.w700)),
        ]),
      ),
    );
  }
}
