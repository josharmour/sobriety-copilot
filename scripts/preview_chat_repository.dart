// Used only by scripts/preview_chat_canvas.sh in its temporary build copy.
import 'package:sobriety_copilot_mobile/data/models/chat_models.dart';
import 'package:sobriety_copilot_mobile/data/repositories/chat_repository_interface.dart';

class PreviewChatRepository implements ChatRepository {
  @override
  Stream<ChatEvent> sendMessage({
    required String message,
    required List<ChatMessage> history,
    List<String>? categories,
    String? tone,
    bool showThinking = false,
    String? userId,
    List<String>? images,
    String? audio,
    String? audioFormat,
    String? clientContext,
  }) async* {
    yield const SourcesEvent([]);
    const reply =
        'This is a local preview reply, not recovery advice. '
        'Your message stays in this demo. The conversation now uses the existing '
        'message layout, composer and controls. Use New conversation to try the quiet entrance again.';
    for (final word in reply.split(' ')) {
      await Future<void>.delayed(const Duration(milliseconds: 28));
      yield TokenEvent('$word ');
    }
    yield const DoneEvent();
  }
}
