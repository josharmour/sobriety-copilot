import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/features/tts/tts_service.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/config/app_config.dart';
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/starter_prompts.dart';
import 'package:sobriety_copilot_mobile/features/chat/chat_notifier.dart';
import 'package:sobriety_copilot_mobile/features/chat/conversations.dart';
import 'package:sobriety_copilot_mobile/features/chat/saved_passages.dart';
import 'package:sobriety_copilot_mobile/features/sheets/about_sheet.dart';
import 'package:sobriety_copilot_mobile/features/sheets/alt_recovery_sheet.dart';
import 'package:sobriety_copilot_mobile/features/sheets/crisis_sheet.dart';
import 'package:sobriety_copilot_mobile/features/sheets/meetings_sheet.dart';
import 'package:sobriety_copilot_mobile/features/sheets/settings_sheet.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

/// The app's main screen: streaming chat with sources, follow-ups, a
/// collapsible thinking panel, suggest autocomplete, the app-bar menu that
/// opens the various sheets, starter prompts when empty, and optional
/// per-message text-to-speech.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

/// Menu actions surfaced by the app-bar overflow menu.
enum _MenuAction { saved, meetings, crisis, altRecovery, settings, about }

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final FocusNode _inputFocus = FocusNode();
  late final AppTts _tts;

  Timer? _debounce;
  String _suggestQuery = '';
  bool _suggestVisible = false;

  /// Id of the message currently being read aloud (null = none).
  String? _speakingId;

  /// Tracks the last assistant message we auto-read so TTS fires only once.
  String? _autoReadId;

  @override
  void initState() {
    super.initState();
    _tts = ref.read(appTtsProvider);
    _tts.onDone = _onTtsDone;
    _inputFocus.addListener(() {
      if (!_inputFocus.hasFocus) {
        setState(() => _suggestVisible = false);
      }
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _input.dispose();
    _scroll.dispose();
    _inputFocus.dispose();
    _tts.onDone = null;
    _tts.stop();
    super.dispose();
  }

  void _onTtsDone() {
    if (mounted) setState(() => _speakingId = null);
  }

  // ── Sending ───────────────────────────────────────────────────────────────

  Future<void> _send([String? text]) async {
    final value = (text ?? _input.text).trim();
    if (value.isEmpty) return;
    final state = ref.read(chatNotifierProvider);
    if (state.isSending) return;

    _input.clear();
    _hideSuggestions();
    FocusScope.of(context).unfocus();

    // Fire and forget; the notifier folds the SSE stream into state.
    unawaited(ref.read(chatNotifierProvider.notifier).sendMessage(value));
    _scrollToBottomSoon();
  }

  void _scrollToBottomSoon() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  // ── Autocomplete ────────────────────────────────────────────────────────────

  void _onInputChanged(String value) {
    _debounce?.cancel();
    final q = value.trim();
    if (q.length < 3) {
      _hideSuggestions();
      setState(() {}); // refresh send-button enabled state
      return;
    }
    setState(() {}); // refresh send-button enabled state immediately
    _debounce = Timer(const Duration(milliseconds: 300), () {
      if (!mounted) return;
      setState(() {
        _suggestQuery = q;
        _suggestVisible = true;
      });
    });
  }

  void _hideSuggestions() {
    if (_suggestVisible || _suggestQuery.isNotEmpty) {
      setState(() {
        _suggestVisible = false;
        _suggestQuery = '';
      });
    }
  }

  void _applySuggestion(Suggestion s) {
    _input.text = s.text;
    _input.selection = TextSelection.collapsed(offset: s.text.length);
    _hideSuggestions();
    _inputFocus.requestFocus();
  }

  // ── Scan / OCR ──────────────────────────────────────────────────────────────

  Future<void> _scanText() async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final picker = ImagePicker();
      final file = await picker.pickImage(source: ImageSource.camera);
      if (file == null) return;
      final recognizer = TextRecognizer();
      final recognized = await recognizer.processImage(
        InputImage.fromFilePath(file.path),
      );
      await recognizer.close();
      final text = recognized.text.replaceAll(RegExp(r'\s+'), ' ').trim();
      if (text.isEmpty) {
        messenger.showSnackBar(
          const SnackBar(content: Text('No text found in the image.')),
        );
        return;
      }
      final existing = _input.text.trim();
      _input.text = existing.isEmpty ? text : '$existing $text';
      _input.selection = TextSelection.collapsed(offset: _input.text.length);
      _inputFocus.requestFocus();
    } catch (e) {
      messenger.showSnackBar(
        SnackBar(content: Text('Could not scan text: $e')),
      );
    }
  }

  // ── Text-to-speech ───────────────────────────────────────────────────────────

  String _cleanForTts(String text) {
    if (text.isEmpty) return '';
    var out = text;
    out = out.replaceAll(RegExp(r'```[\s\S]*?```'), ' ');
    out = out.replaceAllMapped(RegExp(r'`([^`]+)`'), (m) => m[1]!);
    out = out.replaceAll(RegExp(r'!\[[^\]]*\]\([^)]*\)'), ' ');
    out = out.replaceAllMapped(
      RegExp(r'\[([^\]]+)\]\([^)]+\)'),
      (m) => m[1]!,
    );
    out = out.replaceAll(RegExp(r'(\*\*\*|___|\*\*|__|\*|_|~~)'), '');
    out = out.replaceAll(RegExp(r'^\s{0,3}#{1,6}\s+', multiLine: true), '');
    out = out.replaceAll(RegExp(r'^\s{0,3}>\s?', multiLine: true), '');
    out = out.replaceAll(RegExp(r'^\s*[-*+]\s+', multiLine: true), '');
    out = out.replaceAll(RegExp(r'^\s*\d+\.\s+', multiLine: true), '');
    out = out.replaceAll(RegExp(r'<\/?[a-zA-Z][^>]*>'), ' ');
    out = out.replaceAll(RegExp(r'\s+'), ' ').trim();
    return out;
  }

  Future<void> _toggleSpeak(ChatMessage m) async {
    if (_speakingId == m.id) {
      await _tts.stop();
      setState(() => _speakingId = null);
      return;
    }
    final cleaned = _cleanForTts(m.text);
    if (cleaned.isEmpty) return;
    setState(() => _speakingId = m.id);
    await _tts.speak(cleaned);
  }

  Future<void> _maybeAutoRead(ChatState next, bool ttsEnabled) async {
    if (!ttsEnabled || next.messages.isEmpty) return;
    final last = next.messages.last;
    if (!last.isAssistant ||
        last.isStreaming ||
        last.isError ||
        last.text.trim().isEmpty) {
      return;
    }
    if (_autoReadId == last.id) return;
    _autoReadId = last.id;
    await _toggleSpeak(last);
  }

  // ── Sheets / menu ─────────────────────────────────────────────────────────────

  Future<void> _openMenu(_MenuAction action) async {
    switch (action) {
      case _MenuAction.saved:
        await showAppSheet(context, const SavedPassagesSheet());
      case _MenuAction.meetings:
        await showAppSheet(context, const MeetingsSheet());
      case _MenuAction.crisis:
        await showAppSheet(context, const CrisisSheet());
      case _MenuAction.altRecovery:
        await showAppSheet(context, const AltRecoverySheet());
      case _MenuAction.settings:
        await showAppSheet(context, const SettingsSheet());
      case _MenuAction.about:
        await showAppSheet(context, const AboutSheet());
    }
  }

  Future<void> _openConversations() async {
    await showAppSheet(context, const ConversationsSheet());
  }

  void _newChat() {
    ref.read(chatNotifierProvider.notifier).startNew();
    _input.clear();
    _hideSuggestions();
  }

  // ── Source detail ────────────────────────────────────────────────────────────

  Future<void> _showSourceDetail(Source source) async {
    final baseUrl = ref.read(appConfigProvider).baseUrl;
    final saved = ref.read(savedPassagesProvider.notifier);
    await showAppSheet(
      context,
      _SourceDetailSheet(source: source, baseUrl: baseUrl, savedNotifier: saved),
    );
  }

  Future<void> _openUrl(String url) async {
    final messenger = ScaffoldMessenger.of(context);
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok) {
      messenger.showSnackBar(
        const SnackBar(content: Text('Could not open the link.')),
      );
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final config = ref.watch(appConfigProvider);
    final chat = ref.watch(chatNotifierProvider);

    // Auto-scroll + auto-read on new content.
    ref.listen<ChatState>(chatNotifierProvider, (prev, next) {
      _scrollToBottomSoon();
      _maybeAutoRead(next, config.ttsEnabled);
    });

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.menu),
          tooltip: 'Conversations',
          onPressed: _openConversations,
        ),
        title: const Text('Sobriety Copilot'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_comment_outlined),
            tooltip: 'New conversation',
            onPressed: _newChat,
          ),
          PopupMenuButton<_MenuAction>(
            onSelected: _openMenu,
            itemBuilder: (context) => const [
              PopupMenuItem(
                value: _MenuAction.saved,
                child: ListTile(
                  leading: Icon(Icons.bookmark_outline),
                  title: Text('Saved passages'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.meetings,
                child: ListTile(
                  leading: Icon(Icons.groups_outlined),
                  title: Text('Find meetings'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.crisis,
                child: ListTile(
                  leading: Icon(Icons.health_and_safety_outlined),
                  title: Text('Crisis resources'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.altRecovery,
                child: ListTile(
                  leading: Icon(Icons.diversity_3_outlined),
                  title: Text('Alternative recovery'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.settings,
                child: ListTile(
                  leading: Icon(Icons.settings_outlined),
                  title: Text('Settings'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.about,
                child: ListTile(
                  leading: Icon(Icons.info_outline),
                  title: Text('About'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: chat.isEmpty
                ? _StarterView(onPick: _send)
                : _buildMessageList(chat, config),
          ),
          if (_suggestVisible) _buildSuggestions(config),
          _buildInputBar(chat, config),
        ],
      ),
    );
  }

  Widget _buildMessageList(ChatState chat, AppConfig config) {
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.md,
      ),
      itemCount: chat.messages.length,
      itemBuilder: (context, index) {
        final m = chat.messages[index];
        final isLast = index == chat.messages.length - 1;
        return _MessageBubble(
          key: ValueKey(m.id),
          message: m,
          showThinking: config.showThinking,
          ttsEnabled: config.ttsEnabled,
          isSpeaking: _speakingId == m.id,
          showRetry: isLast && m.isAssistant && m.isError,
          onSpeak: () => _toggleSpeak(m),
          onCopy: () => _copy(m.text),
          onRetry: () =>
              ref.read(chatNotifierProvider.notifier).retryLast(),
          onSourceTap: _showSourceDetail,
          onFollowup: _send,
          onLinkTap: _openUrl,
        );
      },
    );
  }

  Future<void> _copy(String text) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Copied')),
      );
    }
  }

  Widget _buildSuggestions(AppConfig config) {
    final async = ref.watch(suggestionsProvider(_suggestQuery));
    final items = async.valueOrNull ?? const <Suggestion>[];
    if (items.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    return Material(
      elevation: 4,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 220),
        child: ListView.separated(
          shrinkWrap: true,
          padding: EdgeInsets.zero,
          itemCount: items.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, i) {
            final s = items[i];
            return ListTile(
              dense: true,
              leading: const Icon(Icons.north_west, size: 16),
              title: Text(s.text, maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: s.source.isEmpty
                  ? null
                  : Text(
                      s.source,
                      style: theme.textTheme.bodySmall,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
              onTap: () => _applySuggestion(s),
            );
          },
        ),
      ),
    );
  }

  Widget _buildInputBar(ChatState chat, AppConfig config) {
    final theme = Theme.of(context);
    final hasText = _input.text.trim().isNotEmpty;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.sm,
          AppSpacing.sm,
          AppSpacing.sm,
          AppSpacing.sm,
        ),
        decoration: BoxDecoration(
          color: theme.colorScheme.surface,
          border: Border(
            top: BorderSide(color: theme.dividerColor.withValues(alpha: 0.5)),
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            IconButton(
              icon: const Icon(Icons.document_scanner_outlined),
              tooltip: 'Scan text',
              onPressed: _scanText,
            ),
            Expanded(
              child: TextField(
                controller: _input,
                focusNode: _inputFocus,
                minLines: 1,
                maxLines: 5,
                textInputAction: TextInputAction.newline,
                onChanged: _onInputChanged,
                decoration: InputDecoration(
                  hintText: 'Ask about recovery, share what is going on...',
                  filled: true,
                  fillColor: theme.colorScheme.surfaceContainerHighest
                      .withValues(alpha: 0.5),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.lg,
                    vertical: AppSpacing.md,
                  ),
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.xs),
            chat.isSending
                ? IconButton.filled(
                    icon: const Icon(Icons.stop),
                    tooltip: 'Stop',
                    onPressed: () =>
                        ref.read(chatNotifierProvider.notifier).stop(),
                  )
                : IconButton.filled(
                    icon: const Icon(Icons.send),
                    tooltip: 'Send',
                    onPressed: hasText ? () => _send() : null,
                  ),
          ],
        ),
      ),
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Starter / empty state
// ════════════════════════════════════════════════════════════════════════════

class _StarterView extends StatelessWidget {
  final void Function(String prompt) onPick;
  const _StarterView({required this.onPick});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final prompts = starterPromptsForNow();
    final reflection = reflectionForToday();
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.xl),
      children: [
        const SizedBox(height: AppSpacing.xl),
        Icon(Icons.explore_outlined, size: 56, color: AppColors.accent),
        const SizedBox(height: AppSpacing.lg),
        Text(
          'Start a Conversation',
          textAlign: TextAlign.center,
          style: theme.textTheme.titleLarge,
        ),
        const SizedBox(height: AppSpacing.md),
        Container(
          padding: const EdgeInsets.all(AppSpacing.lg),
          decoration: BoxDecoration(
            color: AppColors.accentSoft,
            borderRadius: BorderRadius.circular(AppSpacing.radius),
          ),
          child: Text(
            reflection,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              fontStyle: FontStyle.italic,
              color: AppColors.brand,
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.xl),
        ...prompts.map(
          (p) => Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(
                alignment: Alignment.centerLeft,
                padding: const EdgeInsets.all(AppSpacing.lg),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppSpacing.radius),
                ),
              ),
              onPressed: () => onPick(p),
              child: Text(p, textAlign: TextAlign.left),
            ),
          ),
        ),
      ],
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Message bubble
// ════════════════════════════════════════════════════════════════════════════

class _MessageBubble extends StatelessWidget {
  final ChatMessage message;
  final bool showThinking;
  final bool ttsEnabled;
  final bool isSpeaking;
  final bool showRetry;
  final VoidCallback onSpeak;
  final VoidCallback onCopy;
  final VoidCallback onRetry;
  final void Function(Source) onSourceTap;
  final void Function(String) onFollowup;
  final void Function(String) onLinkTap;

  const _MessageBubble({
    super.key,
    required this.message,
    required this.showThinking,
    required this.ttsEnabled,
    required this.isSpeaking,
    required this.showRetry,
    required this.onSpeak,
    required this.onCopy,
    required this.onRetry,
    required this.onSourceTap,
    required this.onFollowup,
    required this.onLinkTap,
  });

  @override
  Widget build(BuildContext context) {
    if (message.isUser) {
      return _userBubble(context);
    }
    return _assistantBubble(context);
  }

  Widget _userBubble(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        margin: const EdgeInsets.only(
          bottom: AppSpacing.md,
          left: AppSpacing.xxl,
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.md,
        ),
        decoration: BoxDecoration(
          color: AppColors.accent,
          borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        ),
        child: Text(
          message.text,
          style: const TextStyle(color: Colors.white),
        ),
      ),
    );
  }

  Widget _assistantBubble(BuildContext context) {
    final streamingEmpty = message.isStreaming && message.text.trim().isEmpty;

    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(
          bottom: AppSpacing.lg,
          right: AppSpacing.xl,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (showThinking && message.thinking.trim().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: ThinkingPanel(
                  thinking: message.thinking,
                  initiallyExpanded: streamingEmpty,
                ),
              ),
            if (streamingEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
                child: LoadingDots(),
              )
            else if (message.text.trim().isNotEmpty)
              _markdown(context),
            if (message.sources.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              _sourceChips(context),
            ],
            if (!message.isStreaming && message.text.trim().isNotEmpty)
              _actions(context),
            if (message.followups.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              _followups(context),
            ],
          ],
        ),
      ),
    );
  }

  Widget _markdown(BuildContext context) {
    final theme = Theme.of(context);
    if (message.isError) {
      return Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.error.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(AppSpacing.radius),
          border: Border.all(color: AppColors.error.withValues(alpha: 0.4)),
        ),
        child: Text(
          message.text,
          style: const TextStyle(color: AppColors.error),
        ),
      );
    }
    return MarkdownBody(
      data: message.text,
      selectable: true,
      styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
        p: theme.textTheme.bodyMedium?.copyWith(height: 1.45),
        a: TextStyle(
          color: AppColors.accent,
          decoration: TextDecoration.underline,
        ),
      ),
      onTapLink: (text, href, title) {
        if (href != null && href.isNotEmpty) onLinkTap(href);
      },
    );
  }

  Widget _sourceChips(BuildContext context) {
    final seen = <String>{};
    final unique = <Source>[];
    for (final s in message.sources) {
      if (seen.add(s.documentKey)) unique.add(s);
    }
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.sm,
      children: [
        for (final s in unique)
          SourceChip(source: s, onTap: () => onSourceTap(s)),
      ],
    );
  }

  Widget _actions(BuildContext context) {
    final theme = Theme.of(context);
    final color = theme.textTheme.bodySmall?.color;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.xs),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            visualDensity: VisualDensity.compact,
            iconSize: 18,
            color: color,
            tooltip: 'Copy',
            icon: const Icon(Icons.copy_outlined),
            onPressed: onCopy,
          ),
          if (ttsEnabled)
            IconButton(
              visualDensity: VisualDensity.compact,
              iconSize: 18,
              color: isSpeaking ? AppColors.accent : color,
              tooltip: isSpeaking ? 'Stop' : 'Read aloud',
              icon: Icon(isSpeaking ? Icons.stop : Icons.volume_up_outlined),
              onPressed: onSpeak,
            ),
          if (showRetry)
            IconButton(
              visualDensity: VisualDensity.compact,
              iconSize: 18,
              color: color,
              tooltip: 'Try again',
              icon: const Icon(Icons.refresh),
              onPressed: onRetry,
            ),
        ],
      ),
    );
  }

  Widget _followups(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader('Keep exploring'),
        const SizedBox(height: AppSpacing.xs),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final q in message.followups.take(3))
              FollowupChip(text: q, onTap: () => onFollowup(q)),
          ],
        ),
      ],
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Source detail bottom sheet
// ════════════════════════════════════════════════════════════════════════════

class _SourceDetailSheet extends StatefulWidget {
  final Source source;
  final String baseUrl;
  final SavedPassagesNotifier savedNotifier;
  const _SourceDetailSheet({
    required this.source,
    required this.baseUrl,
    required this.savedNotifier,
  });

  @override
  State<_SourceDetailSheet> createState() => _SourceDetailSheetState();
}

class _SourceDetailSheetState extends State<_SourceDetailSheet> {
  late bool _saved;

  @override
  void initState() {
    super.initState();
    _saved = widget.savedNotifier.isSaved(widget.source);
  }

  Future<void> _toggleSave() async {
    if (_saved) {
      await widget.savedNotifier.remove(widget.source);
    } else {
      await widget.savedNotifier.save(widget.source);
    }
    if (mounted) setState(() => _saved = !_saved);
  }

  Future<void> _open() async {
    final url = widget.source.renderUrl(
      widget.baseUrl,
      highlight: widget.source.excerpt,
    );
    final uri = Uri.tryParse(url);
    if (uri != null) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = widget.source;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(s.title, style: theme.textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Relevance ${(s.similarity * 100).round()}%',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.md),
            Flexible(
              child: SingleChildScrollView(
                child: Text(
                  s.excerpt,
                  style: theme.textTheme.bodyMedium?.copyWith(height: 1.4),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _toggleSave,
                    icon: Icon(
                      _saved ? Icons.bookmark : Icons.bookmark_outline,
                    ),
                    label: Text(_saved ? 'Saved' : 'Save passage'),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: _open,
                    icon: const Icon(Icons.open_in_new),
                    label: const Text('Open'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
