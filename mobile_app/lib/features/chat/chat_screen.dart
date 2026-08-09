import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sobriety_copilot_mobile/features/tts/tts_service.dart';
import 'package:sobriety_copilot_mobile/features/chat/ocr_scanner.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
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
import 'package:sobriety_copilot_mobile/features/library/offline_reader.dart';
import 'package:sobriety_copilot_mobile/config/capabilities.dart';
import 'package:sobriety_copilot_mobile/features/asr/asr_manager.dart';
import 'package:sobriety_copilot_mobile/features/asr/asr_service.dart';
import 'package:sobriety_copilot_mobile/features/daily/study_themes.dart';
import 'package:sobriety_copilot_mobile/features/meditation/meditation_sheet.dart';
import 'package:sobriety_copilot_mobile/features/daily/today_sheet.dart';
import 'package:sobriety_copilot_mobile/features/milestones/milestone_card.dart';
import 'package:sobriety_copilot_mobile/features/graph/rag_graph_view.dart';
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
enum _MenuAction {
  today,
  meditation,
  saved,
  graph,
  meetings,
  crisis,
  altRecovery,
  settings,
  about,
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final FocusNode _inputFocus = FocusNode();
  late final AppTts _tts;

  Timer? _debounce;
  String _suggestQuery = '';
  bool _suggestVisible = false;

  /// Queued photo attachments as `data:image/...;base64,...` URLs.
  final List<String> _pendingImages = [];

  /// Mic voice input (record → on-device sherpa-onnx ASR → fill the input box).
  final AudioRecorder _recorder = AudioRecorder();
  bool _isRecording = false;
  bool _isTranscribing = false;

  /// Id of the message currently being read aloud (null = none).
  String? _speakingId;

  /// Tracks the last assistant message we auto-read so TTS fires only once.
  String? _autoReadId;

  /// Bumped on new-chat so the starter view remounts with fresh suggestions.
  int _starterGeneration = 0;

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
    _recorder.dispose();
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
    final images = List<String>.from(_pendingImages);
    if (value.isEmpty && images.isEmpty) return;
    final state = ref.read(chatNotifierProvider);
    if (state.isSending) return;

    _input.clear();
    if (_pendingImages.isNotEmpty) setState(() => _pendingImages.clear());
    _hideSuggestions();
    FocusScope.of(context).unfocus();

    // Fire and forget; the notifier folds the SSE stream into state.
    unawaited(ref
        .read(chatNotifierProvider.notifier)
        .sendMessage(value, images: images));
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
      final text = await scanTextFromCamera();
      if (text == null) return;
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
    } on PlatformException catch (e) {
      messenger.showSnackBar(
        SnackBar(
          content: Text(e.code.contains('access_denied')
              ? 'Camera access is turned off for Sobriety Copilot. You can '
                  'enable it in your device Settings.'
              : 'Could not scan text — please try again.'),
        ),
      );
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
            content: Text('Could not scan text — please try again.')),
      );
    }
  }

  // ── Photo attachments ────────────────────────────────────────────────────────

  /// Attach menu: take/choose a photo (sent to the model), or scan text (OCR
  /// into the input box).
  Future<void> _showAttachSheet() async {
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (supportsCameraAndOcr)
              ListTile(
                leading: const Icon(Icons.photo_camera_outlined),
                title: const Text('Take a photo'),
                subtitle: const Text('Ask about what the photo shows'),
                onTap: () => Navigator.pop(ctx, 'camera'),
              ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose a photo'),
              onTap: () => Navigator.pop(ctx, 'gallery'),
            ),
            if (supportsCameraAndOcr)
              ListTile(
                leading: const Icon(Icons.document_scanner_outlined),
                title: const Text('Scan text'),
                subtitle: const Text('Read text from a page into the box'),
                onTap: () => Navigator.pop(ctx, 'scan'),
              ),
          ],
        ),
      ),
    );
    switch (action) {
      case 'camera':
        await _pickImage(ImageSource.camera);
        break;
      case 'gallery':
        await _pickImage(ImageSource.gallery);
        break;
      case 'scan':
        await _scanText();
        break;
    }
  }

  Future<void> _pickImage(ImageSource source) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      if (_pendingImages.length >= 4) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Up to 4 photos at a time.')),
        );
        return;
      }
      final picker = ImagePicker();
      final file = await picker.pickImage(
        source: source,
        maxWidth: 1600,
        imageQuality: 82,
      );
      if (file == null) return;
      final bytes = await file.readAsBytes();
      final ext = file.path.split('.').last.toLowerCase();
      final mime = ext == 'png' ? 'image/png' : 'image/jpeg';
      final dataUrl = 'data:$mime;base64,${base64Encode(bytes)}';
      if (!mounted) return;
      setState(() => _pendingImages.add(dataUrl));
    } on PlatformException catch (e) {
      messenger.showSnackBar(
        SnackBar(
          content: Text(e.code.contains('access_denied')
              ? 'Camera or photo access is turned off for Sobriety Copilot. '
                  'You can enable it in your device Settings.'
              : 'Could not attach photo — please try again.'),
        ),
      );
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
            content: Text('Could not attach photo — please try again.')),
      );
    }
  }

  // ── Mic voice input (local transcription via gemma) ──────────────────────────

  Future<void> _toggleMic() async {
    if (_isTranscribing) return;
    if (_isRecording) {
      await _finishRecording();
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    // Dictation is fully on-device; without the model installed the mic can't
    // produce text, so point at the download instead of asking for mic access.
    if (ref.read(asrManagerProvider.notifier).installedDir() == null) {
      messenger.showSnackBar(
        const SnackBar(
          content: Text(
            'Voice dictation runs entirely on this device. Download the '
            'dictation model in Settings → Private Mode to use the mic.',
          ),
        ),
      );
      return;
    }
    try {
      if (!await _recorder.hasPermission()) {
        messenger.showSnackBar(
          const SnackBar(
            content: Text(
              'Microphone access is turned off for Sobriety Copilot. You can '
              'enable it in your device Settings.',
            ),
          ),
        );
        return;
      }
      final dir = await getTemporaryDirectory();
      final path =
          '${dir.path}/voice_${DateTime.now().millisecondsSinceEpoch}.wav';
      await _recorder.start(
        const RecordConfig(
          encoder: AudioEncoder.wav,
          sampleRate: 16000,
          numChannels: 1,
        ),
        path: path,
      );
      if (!mounted) return;
      setState(() => _isRecording = true);
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
            content: Text('Could not start recording — please try again.')),
      );
    }
  }

  Future<void> _finishRecording() async {
    final messenger = ScaffoldMessenger.of(context);
    String? path;
    try {
      path = await _recorder.stop();
    } catch (_) {}
    if (!mounted) return;
    setState(() => _isRecording = false);
    if (path == null) return;
    setState(() => _isTranscribing = true);
    try {
      // Fully on-device — audio never leaves the phone. The mic button is
      // gated on the model being installed, so asrDir is normally non-null.
      final asrDir = ref.read(asrManagerProvider.notifier).installedDir();
      if (asrDir == null) {
        messenger.showSnackBar(
          const SnackBar(
            content: Text(
              'Voice dictation runs entirely on this device. Download the '
              'dictation model in Settings → Private Mode to use the mic.',
            ),
          ),
        );
        return;
      }
      final text = await transcribeWavFile(wavPath: path, modelDir: asrDir);
      if (!mounted) return;
      if (text.isNotEmpty) {
        final existing = _input.text.trim();
        _input.text = existing.isEmpty ? text : '$existing $text';
        _input.selection =
            TextSelection.collapsed(offset: _input.text.length);
        _inputFocus.requestFocus();
        _onInputChanged(_input.text);
      } else {
        messenger.showSnackBar(
          const SnackBar(content: Text("Didn't catch that — try again.")),
        );
      }
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
            content: Text('Could not transcribe that — please try again.')),
      );
    } finally {
      if (mounted) setState(() => _isTranscribing = false);
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
      case _MenuAction.today:
        await showAppSheet(context, const TodaySheet());
      case _MenuAction.meditation:
        await showAppSheet(context, const MeditationSheet());
      case _MenuAction.saved:
        await showAppSheet(context, const SavedPassagesSheet());
      case _MenuAction.graph:
        await Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => RagGraphScreen(
              initialQuery: 'The Twelve Steps',
              onSelectPrompt: (prompt) => _send(prompt),
            ),
          ),
        );
      case _MenuAction.meetings:
        // Map + results want the full screen.
        await showAppSheet(context, const MeetingsSheet(), initialSize: 0.95);
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
    // Remount the starter view so a fresh hand of suggestions is drawn —
    // tapping the title / new-conversation repeatedly cycles the rotation.
    setState(() => _starterGeneration++);
  }

  // ── Source detail ────────────────────────────────────────────────────────────

  Future<void> _showSourceDetail(Source source, List<Source> allSources) async {
    final baseUrl = ref.read(appConfigProvider).baseUrl;
    final saved = ref.read(savedPassagesProvider.notifier);
    await showAppSheet(
      context,
      _SourceDetailSheet(
        initialSource: source,
        allSources: allSources,
        baseUrl: baseUrl,
        savedNotifier: saved,
      ),
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
        title: GestureDetector(
          onTap: _newChat,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Flexible(
                child: Text('Sobriety Copilot', overflow: TextOverflow.fade),
              ),
              if (ref.watch(privateModeActiveProvider)) ...[
                const SizedBox(width: AppSpacing.sm),
                Tooltip(
                  message:
                      'Private Mode — answering on this phone. Nothing leaves the device.',
                  child: InkWell(
                    borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
                    onTap: () => _openMenu(_MenuAction.settings),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.sm,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.accent.withValues(alpha: 0.15),
                        border: Border.all(color: AppColors.accent),
                        borderRadius:
                            BorderRadius.circular(AppSpacing.radiusLg),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.shield_outlined,
                              size: 13, color: AppColors.accent),
                          SizedBox(width: 3),
                          Text(
                            'Private',
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              color: AppColors.accent,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
        actions: [
          Container(
            margin: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.25),
              borderRadius: BorderRadius.circular(AppSpacing.radius),
              border: Border.all(color: AppColors.accent, width: 1.2),
            ),
            child: IconButton(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
              icon: const Icon(Icons.bubble_chart, color: AppColors.accent, size: 20),
              tooltip: 'Knowledge Graph',
              onPressed: () => _openMenu(_MenuAction.graph),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.add_comment_outlined),
            tooltip: 'New conversation',
            onPressed: _newChat,
          ),
          PopupMenuButton<_MenuAction>(
            onSelected: _openMenu,
            itemBuilder: (context) => const [
              PopupMenuItem(
                value: _MenuAction.today,
                child: ListTile(
                  leading: Icon(Icons.wb_twilight_outlined),
                  title: Text('Today'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.meditation,
                child: ListTile(
                  leading: Icon(Icons.self_improvement_outlined),
                  title: Text('Meditation'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.saved,
                child: ListTile(
                  leading: Icon(Icons.bookmark_outline),
                  title: Text('Saved passages'),
                  contentPadding: EdgeInsets.zero,
                ),
              ),
              PopupMenuItem(
                value: _MenuAction.graph,
                child: ListTile(
                  leading: Icon(Icons.hub_outlined),
                  title: Text('Knowledge Graph'),
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
                  leading: Icon(Icons.alt_route_outlined),
                  title: Text('Other recovery paths'),
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
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 800),
          child: Column(
            children: [
              Expanded(
                child: chat.isEmpty
                    ? _StarterView(
                        key: ValueKey(_starterGeneration),
                        onPick: _send,
                        studySuggestions: ref.watch(studySuggestionsProvider),
                      )
                    : _buildMessageList(chat, config),
              ),
              if (_suggestVisible) _buildSuggestions(config),
              _buildInputBar(chat, config),
            ],
          ),
        ),
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
          onSourceTap: (source, allSources) =>
              _showSourceDetail(source, allSources),
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
    final canSend = hasText || _pendingImages.isNotEmpty;
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
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_pendingImages.isNotEmpty) _buildAttachmentPreview(theme),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                IconButton(
                  icon: const Icon(Icons.add_photo_alternate_outlined),
                  tooltip: 'Attach a photo or scan text',
                  onPressed: _showAttachSheet,
                ),
                if (supportsMicInput)
                  _isTranscribing
                      ? const IconButton(
                          onPressed: null,
                          icon: SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                        )
                      : IconButton(
                          icon:
                              Icon(_isRecording ? Icons.stop : Icons.mic_none),
                          color:
                              _isRecording ? theme.colorScheme.error : null,
                          tooltip:
                              _isRecording ? 'Stop recording' : 'Voice input',
                          onPressed: _toggleMic,
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
                      hintText: _isRecording
                          ? 'Listening…'
                          : 'Ask about recovery, share what is going on...',
                      filled: true,
                      fillColor: theme.colorScheme.surfaceContainerHighest
                          .withValues(alpha: 0.5),
                      border: OutlineInputBorder(
                        borderRadius:
                            BorderRadius.circular(AppSpacing.radiusLg),
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
                        onPressed: canSend ? () => _send() : null,
                      ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                TextButton.icon(
                  icon: const Icon(Icons.groups_outlined, size: 14),
                  label: const Text('Find a meeting'),
                  style: TextButton.styleFrom(
                    foregroundColor: theme.colorScheme.onSurfaceVariant,
                    minimumSize: Size.zero,
                    padding:
                        const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    textStyle: theme.textTheme.bodySmall,
                  ),
                  onPressed: () => _openMenu(_MenuAction.meetings),
                ),
                TextButton.icon(
                  icon: const Icon(Icons.wb_twilight_outlined, size: 14),
                  label: const Text('Today'),
                  style: TextButton.styleFrom(
                    foregroundColor: theme.colorScheme.onSurfaceVariant,
                    minimumSize: Size.zero,
                    padding:
                        const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    textStyle: theme.textTheme.bodySmall,
                  ),
                  onPressed: () => _openMenu(_MenuAction.today),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// Horizontal strip of queued photo thumbnails, each with a remove button.
  Widget _buildAttachmentPreview(ThemeData theme) {
    return Container(
      height: 72,
      alignment: Alignment.centerLeft,
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: _pendingImages.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
        itemBuilder: (ctx, i) {
          final bytes = base64Decode(_pendingImages[i].split(',').last);
          return SizedBox(
            width: 64,
            height: 64,
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(AppSpacing.radius),
                  child: Image.memory(
                    bytes,
                    width: 64,
                    height: 64,
                    fit: BoxFit.cover,
                  ),
                ),
                Positioned(
                  top: -8,
                  right: -8,
                  child: IconButton(
                    iconSize: 20,
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                    icon: const Icon(Icons.cancel),
                    color: theme.colorScheme.error,
                    tooltip: 'Remove',
                    onPressed: () =>
                        setState(() => _pendingImages.removeAt(i)),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Starter / empty state
// ════════════════════════════════════════════════════════════════════════════

class _StarterView extends ConsumerStatefulWidget {
  final void Function(String prompt) onPick;
  final List<StudySuggestion> studySuggestions;
  const _StarterView({
    super.key,
    required this.onPick,
    this.studySuggestions = const [],
  });

  @override
  ConsumerState<_StarterView> createState() => _StarterViewState();
}

class _StarterViewState extends ConsumerState<_StarterView> {
  late final List<String> _prompts;

  @override
  void initState() {
    super.initState();
    // Rotation with a persisted no-repeat window — a fresh hand of prompts
    // every empty-chat view, no repeats until the pool cycles.
    _prompts = pickStarterPrompts(ref.read(sharedPreferencesProvider));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isLight = theme.brightness == Brightness.light;
    final prompts = _prompts;
    final reflection = reflectionForToday();

    final bgDecoration = isLight
        ? BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                theme.colorScheme.surface,
                theme.colorScheme.surfaceContainerHighest.withAlpha(180),
              ],
            ),
          )
        : const BoxDecoration(
            image: DecorationImage(
              image: AssetImage('assets/icon/app_icon.jpg'),
              fit: BoxFit.cover,
              alignment: Alignment.center,
            ),
          );

    final overlayDecoration = isLight
        ? const BoxDecoration(color: Colors.transparent)
        : BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Colors.black.withAlpha(20),
                Colors.black.withAlpha(160),
                Colors.black.withAlpha(240),
              ],
              stops: const [0.0, 0.5, 1.0],
            ),
          );

    final titleColor = isLight ? theme.colorScheme.onSurface : Colors.white;
    final cardBg = isLight ? theme.colorScheme.surface : Colors.black.withAlpha(120);
    final cardBorder = isLight ? theme.colorScheme.outlineVariant : Colors.white24;
    final reflectionTextColor = isLight ? theme.colorScheme.onSurface : Colors.white;
    final btnFgColor = isLight ? theme.colorScheme.onSurface : Colors.white;
    final btnBorderColor = isLight ? theme.colorScheme.outlineVariant : Colors.white54;
    final btnBgColor = isLight ? theme.colorScheme.surface : Colors.black.withAlpha(120);

    return Container(
      decoration: bgDecoration,
      child: Container(
        decoration: overlayDecoration,
        child: LayoutBuilder(
          builder: (context, constraints) {
            return SingleChildScrollView(
              padding: const EdgeInsets.all(AppSpacing.xl),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  minHeight: constraints.maxHeight > 80 ? constraints.maxHeight - 80 : 0,
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Start a Conversation',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineMedium?.copyWith(
                        color: titleColor,
                        fontWeight: FontWeight.bold,
                        shadows: isLight
                            ? null
                            : [
                                const Shadow(
                                  color: Colors.black87,
                                  blurRadius: 8,
                                  offset: Offset(0, 2),
                                ),
                              ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.md),
                    Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 600),
                        child: Container(
                          padding: const EdgeInsets.all(AppSpacing.lg),
                          decoration: BoxDecoration(
                            color: cardBg,
                            borderRadius: BorderRadius.circular(AppSpacing.radius),
                            border: Border.all(color: cardBorder),
                            boxShadow: isLight
                                ? [
                                    BoxShadow(
                                      color: Colors.black.withAlpha(12),
                                      blurRadius: 8,
                                      offset: const Offset(0, 2),
                                    ),
                                  ]
                                : null,
                          ),
                          child: Text(
                            reflection,
                            textAlign: TextAlign.center,
                            style: theme.textTheme.bodyMedium?.copyWith(
                              fontStyle: FontStyle.italic,
                              color: reflectionTextColor,
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.md),
                    const MilestoneCard(),
                    const SizedBox(height: AppSpacing.xl),
                    ...prompts.map(
                      (p) => Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                        child: Center(
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 600),
                            child: SizedBox(
                              width: double.infinity,
                              child: OutlinedButton(
                                style: OutlinedButton.styleFrom(
                                  alignment: Alignment.centerLeft,
                                  foregroundColor: btnFgColor,
                                  side: BorderSide(color: btnBorderColor),
                                  backgroundColor: btnBgColor,
                                  padding: const EdgeInsets.all(AppSpacing.lg),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(AppSpacing.radius),
                                  ),
                                  elevation: isLight ? 1 : 0,
                                ),
                                onPressed: () => widget.onPick(p),
                                child: Text(p, textAlign: TextAlign.left),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          }
        ),
      ),
    );
  }
}

class _DenoisingProgress extends StatelessWidget {
  final int step;
  final int total;

  const _DenoisingProgress({required this.step, required this.total});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final percent = total > 0 ? (step + 1) / total : 0.0;
    final cleanPercent = percent.clamp(0.0, 1.0);

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.auto_awesome,
                size: 14,
                color: AppColors.accent,
              ),
              const SizedBox(width: AppSpacing.xs),
              Text(
                'denoising — pass ${step + 1}/$total',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppColors.accent,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: cleanPercent,
              minHeight: 4,
              backgroundColor: theme.colorScheme.outlineVariant,
              valueColor: const AlwaysStoppedAnimation<Color>(AppColors.accent),
            ),
          ),
        ],
      ),
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
  final void Function(Source, List<Source>) onSourceTap;
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
    final hasImages = message.imageThumbs.isNotEmpty;
    final hasText = message.text.trim().isNotEmpty;
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
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (hasImages)
              Padding(
                padding: EdgeInsets.only(bottom: hasText ? AppSpacing.sm : 0),
                child: Wrap(
                  spacing: AppSpacing.xs,
                  runSpacing: AppSpacing.xs,
                  alignment: WrapAlignment.end,
                  children: [
                    for (final url in message.imageThumbs)
                      ClipRRect(
                        borderRadius: BorderRadius.circular(AppSpacing.radius),
                        child: Image.memory(
                          base64Decode(url.split(',').last),
                          width: 140,
                          height: 140,
                          fit: BoxFit.cover,
                        ),
                      ),
                  ],
                ),
              ),
            if (hasText)
              Text(
                message.text,
                style: const TextStyle(color: Colors.white),
              ),
          ],
        ),
      ),
    );
  }

  Widget _assistantBubble(BuildContext context) {
    final hasText = message.text.trim().isNotEmpty;
    final hasDiffusion = message.isDenoising && message.diffusionContent != null && message.diffusionContent!.trim().isNotEmpty;
    final streamingEmpty = message.isStreaming && !hasText && !hasDiffusion;

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
            if (message.isDenoising && message.diffusionStep != null && message.diffusionTotal != null)
              _DenoisingProgress(
                step: message.diffusionStep!,
                total: message.diffusionTotal!,
              ),
            if (streamingEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
                child: LoadingDots(),
              )
            else if (hasDiffusion)
              _diffusionBody(context)
            else if (hasText)
              _markdown(context),
            if (message.sources.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              _sourceChips(context),
            ],
            if (!message.isStreaming && hasText)
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

  Widget _diffusionBody(BuildContext context) {
    final theme = Theme.of(context);
    final raw = message.diffusionContent ?? '';
    final cleaned = raw.replaceAll(RegExp(r'<(?:eos|pad|unk)>'), '');

    return Opacity(
      opacity: 0.7,
      child: Text(
        cleaned,
        style: theme.textTheme.bodyMedium?.copyWith(
          height: 1.45,
          fontStyle: FontStyle.italic,
        ),
      ),
    );
  }

  String _enrichTextWithSourceLinks(String text, List<Source> sources) {
    var processed = text;
    final unique = <String, Source>{};
    for (final s in sources) {
      final t = s.title.toLowerCase();
      if (t.length >= 4) {
        unique[t] = s;
      }
    }

    final sortedTitles = unique.keys.toList()
      ..sort((a, b) => b.length.compareTo(a.length));

    for (final title in sortedTitles) {
      final source = unique[title]!;
      final escTitle = RegExp.escape(title).replaceAll(RegExp(r' +'), r'\s+');
      final pattern = RegExp('\\b$escTitle(?:s)?\\b', caseSensitive: false);

      processed = processed.replaceAllMapped(pattern, (match) {
        final matchedText = match.group(0)!;
        final index = match.start;
        if (index > 0 && processed[index - 1] == '[') {
          return matchedText;
        }
        final afterIndex = match.end;
        if (afterIndex < processed.length &&
            processed.substring(afterIndex).startsWith('](')) {
          return matchedText;
        }
        final docKey = Uri.encodeComponent(source.documentKey);
        return '[$matchedText](source://$docKey)';
      });
    }
    return processed;
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
    final enrichedData = _enrichTextWithSourceLinks(message.text, message.sources);
    return MarkdownBody(
      data: enrichedData,
      selectable: true,
      styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
        p: theme.textTheme.bodyMedium?.copyWith(height: 1.45),
        a: TextStyle(
          color: AppColors.accent,
          decoration: TextDecoration.underline,
        ),
      ),
      onTapLink: (text, href, title) {
        if (href != null && href.startsWith('source://')) {
          final docKey = Uri.decodeComponent(href.replaceFirst('source://', ''));
          final seen = <String>{};
          final unique = <Source>[];
          for (final s in message.sources) {
            if (seen.add(s.documentKey)) unique.add(s);
          }
          final source = unique.firstWhere(
            (s) => s.documentKey == docKey,
            orElse: () => unique.first,
          );
          onSourceTap(source, unique);
        } else if (href != null && href.isNotEmpty) {
          onLinkTap(href);
        }
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
      crossAxisAlignment: WrapCrossAlignment.start,
      children: [
        for (final s in unique)
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              SourceChip(source: s, onTap: () => onSourceTap(s, unique)),
              if (s.concepts.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.xs),
                _ConceptTags(
                  concepts: s.concepts,
                  onTap: () => onSourceTap(s, unique),
                ),
              ],
            ],
          ),
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

/// Small labelled chips showing a source's conceptual tags (e.g. "step two",
/// "surrender"). Tapping one opens the source detail sheet. Styled with the
/// lighthouse palette; renders nothing when [concepts] is empty.
class _ConceptTags extends StatelessWidget {
  final List<String> concepts;
  final VoidCallback? onTap;
  const _ConceptTags({required this.concepts, this.onTap});

  @override
  Widget build(BuildContext context) {
    if (concepts.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final borderCol =
        isDark ? const Color(0xFF2E4A63) : const Color(0xFFBFDCE9);
    final labelColor = AppColors.accent;
    return Wrap(
      spacing: AppSpacing.xs,
      runSpacing: AppSpacing.xs,
      children: [
        for (final concept in concepts)
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm,
              vertical: 2,
            ),
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.10),
              borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
              border: Border.all(color: borderCol),
            ),
            child: Text(
              concept,
              style: theme.textTheme.labelSmall?.copyWith(
                color: labelColor,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
      ],
    );
  }
}

class _SourceDetailSheet extends ConsumerStatefulWidget {
  final Source initialSource;
  final List<Source> allSources;
  final String baseUrl;
  final SavedPassagesNotifier savedNotifier;
  const _SourceDetailSheet({
    required this.initialSource,
    required this.allSources,
    required this.baseUrl,
    required this.savedNotifier,
  });

  @override
  ConsumerState<_SourceDetailSheet> createState() => _SourceDetailSheetState();
}

class _SourceDetailSheetState extends ConsumerState<_SourceDetailSheet> {
  late PageController _pageController;
  late int _currentPage;
  final Map<int, bool> _savedMap = {};

  @override
  void initState() {
    super.initState();
    final idx = widget.allSources.indexWhere((s) => s.documentKey == widget.initialSource.documentKey);
    _currentPage = idx >= 0 ? idx : 0;
    _pageController = PageController(initialPage: _currentPage);
    for (var i = 0; i < widget.allSources.length; i++) {
      _savedMap[i] = widget.savedNotifier.isSaved(widget.allSources[i]);
    }
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _toggleSave(int index) async {
    final s = widget.allSources[index];
    final isSaved = _savedMap[index] ?? false;
    if (isSaved) {
      await widget.savedNotifier.remove(s);
    } else {
      await widget.savedNotifier.save(s);
    }
    if (mounted) {
      setState(() {
        _savedMap[index] = !isSaved;
      });
    }
  }

  Future<void> _open(Source s) async {
    if (s.docId != null) {
      final libraryRepo = ref.read(libraryRepositoryProvider);
      final installed = await libraryRepo.isPackInstalled;
      if (installed && mounted) {
        Navigator.pop(context);
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => OfflineReaderScreen(
              docId: s.docId!,
              title: s.title,
              highlightBlockIds: s.blockIds,
            ),
          ),
        );
        return;
      }
    }

    final url = s.renderUrl(
      widget.baseUrl,
      highlight: s.excerpt,
    );
    final uri = Uri.tryParse(url);
    if (uri != null) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  /// Fetches /api/deepdive for this source and shows the assembled Step
  /// section(s) + an option to generate an AI study guide. Uses live AppConfig.
  Future<void> _deepDive(Source s) async {
    final baseUrl = ref.read(appConfigProvider).baseUrl;
    final client = ref.read(httpClientProvider);
    final root = baseUrl.replaceAll(RegExp(r'/+$'), '');
    // Prefer the server-provided manifest doc_id (a slug like
    // "twelve-steps-and-twelve-traditions"). Fall back to the bare filename
    // stem of the source URL when doc_id is absent (e.g. legacy bundles).
    String doc = s.docId ?? '';
    if (doc.isEmpty) {
      final dir = s.url.replaceFirst('/api/documents/', '').trim();
      // Strip any leading category dir and file extension to a bare stem.
      final stem = dir.split('/').last.replaceFirst(RegExp(r'\.[^.]+$'), '');
      doc = stem;
    }
    final uri = Uri.parse('$root/api/deepdive').replace(
      queryParameters: {
        if (doc.isNotEmpty) 'doc': doc,
      },
    );
    DeepDive? deepDive;
    try {
      final res = await client.get(uri).timeout(const Duration(seconds: 15));
      if (res.statusCode < 200 || res.statusCode >= 300) {
        throw Exception('Deep dive unavailable (${res.statusCode}).');
      }
      final json = jsonDecode(res.body) as Map<String, dynamic>;
      deepDive = DeepDive.fromJson(json);
      if (deepDive.sections.isEmpty) {
        throw Exception('No Step sections found for this source.');
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString())),
      );
      return;
    }
    if (!mounted) return;
    await showAppSheet(
      context,
      _DeepDiveSheet(deepDive: deepDive, doc: doc, baseUrl: baseUrl),
      initialSize: 0.85,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final total = widget.allSources.length;

    return SafeArea(
      child: Container(
        height: 450,
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Column(
          children: [
            if (total > 1)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    IconButton(
                      icon: const Icon(Icons.chevron_left),
                      onPressed: _currentPage > 0
                          ? () => _pageController.previousPage(
                                duration: const Duration(milliseconds: 300),
                                curve: Curves.easeInOut,
                              )
                          : null,
                    ),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: List.generate(total, (index) {
                        final isCurrent = index == _currentPage;
                        return AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          margin: const EdgeInsets.symmetric(horizontal: 4),
                          width: isCurrent ? 12 : 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: isCurrent ? AppColors.accent : theme.colorScheme.outlineVariant,
                            borderRadius: BorderRadius.circular(4),
                          ),
                        );
                      }),
                    ),
                    IconButton(
                      icon: const Icon(Icons.chevron_right),
                      onPressed: _currentPage < total - 1
                          ? () => _pageController.nextPage(
                                duration: const Duration(milliseconds: 300),
                                curve: Curves.easeInOut,
                              )
                          : null,
                    ),
                  ],
                ),
              ),
            Expanded(
              child: PageView.builder(
                controller: _pageController,
                onPageChanged: (page) {
                  setState(() => _currentPage = page);
                },
                itemCount: total,
                itemBuilder: (context, index) {
                  final s = widget.allSources[index];
                  final isSaved = _savedMap[index] ?? false;
                  return Padding(
                    padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          s.title,
                          style: theme.textTheme.titleMedium,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: AppSpacing.xs),
                        Text(
                          'Relevance ${(s.similarity * 100).round()}% | Source ${index + 1} of $total',
                          style: theme.textTheme.bodySmall,
                        ),
                        if (s.concepts.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.sm),
                          _ConceptTags(concepts: s.concepts),
                        ],
                        const SizedBox(height: AppSpacing.md),
                        Expanded(
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
                                onPressed: () => _toggleSave(index),
                                icon: Icon(
                                  isSaved ? Icons.bookmark : Icons.bookmark_outline,
                                ),
                                label: Text(isSaved ? 'Saved' : 'Save passage'),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: FilledButton.icon(
                                onPressed: () => _open(s),
                                icon: const Icon(Icons.open_in_new),
                                label: const Text('Open'),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: AppSpacing.sm),
                        SizedBox(
                          width: double.infinity,
                          child: TextButton.icon(
                            onPressed: () => _deepDive(s),
                            icon: const Icon(Icons.menu_book),
                            label: const Text('Deep dive · read the full Step section'),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Deep dive bottom sheet
// ════════════════════════════════════════════════════════════════════════════

/// Shows the assembled Step section(s) returned by GET /api/deepdive
/// (read/view side) plus an optional AI-generated study guide.
class _DeepDiveSheet extends ConsumerStatefulWidget {
  final DeepDive deepDive;
  final String doc;
  final String baseUrl;
  const _DeepDiveSheet({
    required this.deepDive,
    required this.doc,
    required this.baseUrl,
  });

  @override
  ConsumerState<_DeepDiveSheet> createState() => _DeepDiveSheetState();
}

class _DeepDiveSheetState extends ConsumerState<_DeepDiveSheet> {
  bool _generating = false;
  DeepDiveGeneration? _generation;
  String? _error;

  String get _docTitle =>
      widget.deepDive.title?.isNotEmpty == true ? widget.deepDive.title! : 'Deep dive';

  Future<void> _generate() async {
    setState(() {
      _generating = true;
      _error = null;
    });
    try {
      final gen = await _generateDeepDiveImpl();
      if (!mounted) return;
      setState(() {
        _generation = gen;
        _generating = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _generating = false;
        _error = e.toString();
      });
    }
  }

  Future<DeepDiveGeneration> _generateDeepDiveImpl() async {
    final client = ref.read(httpClientProvider);
    final root = widget.baseUrl.replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$root/api/deepdive/generate').replace(
      queryParameters: {
        if (widget.doc.isNotEmpty) 'doc': widget.doc,
      },
    );
    final res = await client.post(uri).timeout(const Duration(seconds: 60));
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('Generation unavailable (${res.statusCode}).');
    }
    final json = jsonDecode(res.body) as Map<String, dynamic>;
    return DeepDiveGeneration.fromJson(json);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final sections = widget.deepDive.sections;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.md,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_docTitle, style: theme.textTheme.titleLarge),
            const SizedBox(height: AppSpacing.xs),
            Text(
              widget.deepDive.sections.length == 1
                  ? (widget.deepDive.requestedSection?.isNotEmpty == true
                      ? 'Full text · ${widget.deepDive.requestedSection}'
                      : 'Full Step section')
                  : '${sections.length} Step sections',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.md),
            // AI study guide
            _aiGuideSection(context),
            const SizedBox(height: AppSpacing.md),
            Expanded(
              child: ListView(
                children: [
                  for (final section in sections) _deepDiveSection(context, section),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _aiGuideSection(BuildContext context) {
    final theme = Theme.of(context);
    if (_generating) {
      return Row(
        children: [
          const SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text('Writing your study guide…', style: theme.textTheme.bodyMedium),
        ],
      );
    }
    if (_generation != null) {
      final g = _generation!;
      return Card(
        color: AppColors.highlightBg(Theme.of(context).brightness == Brightness.dark),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('✨ AI Study Guide', style: theme.textTheme.titleMedium),
              const SizedBox(height: AppSpacing.xs),
              Text(
                g.sectionTitle?.isNotEmpty == true ? (g.sectionTitle!) : 'Deep dive',
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(g.text, style: theme.textTheme.bodyMedium?.copyWith(height: 1.5)),
            ],
          ),
        ),
      );
    }
    if (_error != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
            child: Text(
              _error!,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.error,
              ),
            ),
          ),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _generate,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ),
        ],
      );
    }
    // CTA
    return SizedBox(
      width: double.infinity,
      child: FilledButton.icon(
        onPressed: _generate,
        icon: const Icon(Icons.auto_awesome),
        label: const Text('Generate AI study guide for the whole Step'),
      ),
    );
  }

  Widget _deepDiveSection(BuildContext context, DeepDiveSection section) {
    final theme = Theme.of(context);
    final title = section.title?.isNotEmpty == true
        ? section.title!
        : 'Section';
    final wordCount = section.wordCount;
    final body = section.fullText.isNotEmpty ? section.fullText : section.preview;
    final isFull = section.fullText.isNotEmpty;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Flexible(
                child: Text(
                  title,
                  style: theme.textTheme.titleMedium,
                ),
              ),
              if (wordCount != null) ...[
                const SizedBox(width: AppSpacing.sm),
                Text(
                  '$wordCount words',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            body,
            style: theme.textTheme.bodyMedium?.copyWith(height: 1.45),
          ),
          if (isFull)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.sm),
              child: Text(
                '— full section —',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppColors.accent,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

