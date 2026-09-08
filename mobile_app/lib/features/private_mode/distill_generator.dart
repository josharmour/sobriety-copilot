// FR11 Wave B — one-shot on-device distillation bridge (Private Mode).
//
// Exposes [localDistillGenerator], a nullable one-shot generator that runs the
// ALREADY-loaded flutter_gemma model over a distillation prompt and returns
// the FULL completion as a single string (no streaming). It mirrors
// local_chat_repository.dart's model drive exactly (install from the resolved
// model file -> getActiveModel -> session chat -> collect TextResponse
// tokens); read-only — this file never modifies model_manager.dart or
// local_chat_repository.dart.
//
// Graceful degradation: returns null when the platform cannot run the local
// model at all (web) or when Private Mode is off, so
// [DistillTransport.forBackend] falls back to the server passthrough. When
// the model FILE is missing at call time the closure throws
// [MemoryDistillError] — the ChatNotifier distillation hook swallows it
// silently (debugPrint only), so a missing model can never disturb chat.
//
// NOTE on "one-shot": flutter_gemma's InferenceModel is session-based
// (createChat -> addQuery -> generateChatResponseAsync), so a one-shot here
// means complete-the-session and return the collected output.

import 'dart:io';

import 'package:flutter_gemma/flutter_gemma.dart';

import 'package:sobriety_copilot_mobile/features/personal_memory/memory_distiller.dart'
    show MemoryDistillError;
import 'package:sobriety_copilot_mobile/features/private_mode/model_manager.dart'
    show PrivateModelNotifier, privateModeSupported;

/// Tiny system instruction reinforcing the JSON-only contract. The prompt
/// itself (kMemoryDistillPrompt) already demands strict JSON; this keeps the
/// small on-device model from drifting into prose.
const String _kDistillSystemInstruction =
    'You are a memory-extraction helper for a recovery app. Extract durable '
    'facts and unfinished topics from the conversation and reply with STRICT '
    'JSON only, exactly matching the requested schema. Never copy message '
    'bodies verbatim.';

/// Max characters collected from the on-device model (runaway guard).
const int _kMaxDistillChars = 800;

/// Returns a one-shot distillation generator for the current Private Mode
/// state, or null when the local model cannot run (web) or Private Mode is
/// off — callers then fall back to the server passthrough.
Future<String> Function(String prompt)? localDistillGenerator({
  bool privateModeActive = true,
}) {
  if (!privateModeSupported || !privateModeActive) return null;
  return _oneShotLocalDistill;
}

Future<String> _oneShotLocalDistill(String prompt) async {
  final file = await PrivateModelNotifier.resolveModelFile();
  if (file == null) {
    throw MemoryDistillError(
      'local model not installed — distillation skipped',
    );
  }
  try {
    final model = await _loadModel(file);
    final chat = await model.createChat(
      temperature: 0.7,
      topK: 40,
      topP: 0.95,
      tokenBuffer: 512,
      systemInstruction: _kDistillSystemInstruction,
      modelType: ModelType.gemmaIt,
      isThinking: false,
    );
    await chat.addQuery(Message.text(text: prompt, isUser: true));
    final buf = StringBuffer();
    await for (final response in chat.generateChatResponseAsync()) {
      if (response is TextResponse) {
        buf.write(response.token);
        if (buf.length > _kMaxDistillChars) break; // runaway guard
      }
    }
    try {
      await chat.close();
    } catch (_) {}
    return buf.toString();
  } catch (e) {
    if (e is MemoryDistillError) rethrow;
    throw MemoryDistillError('local distillation failed: $e');
  }
}

/// Loads the shared on-device model, mirroring LocalChatRepository._ensureModel
/// (GPU first, CPU fallback). The model stays loaded process-wide — only the
/// session chat is closed after a run.
Future<InferenceModel> _loadModel(File file) async {
  final attempts = <PreferredBackend>[
    PreferredBackend.gpu,
    PreferredBackend.cpu,
  ];
  Object? lastError;
  for (final backend in attempts) {
    try {
      await FlutterGemma.installModel(
        modelType: ModelType.gemmaIt,
        fileType: ModelFileType.litertlm,
      ).fromFile(file.path).install();
      return await FlutterGemma.getActiveModel(
        maxTokens: 1024,
        preferredBackend: backend,
      );
    } catch (e) {
      lastError = e;
    }
  }
  throw MemoryDistillError('could not load on-device model: $lastError');
}
