/// Catalog of downloadable neural TTS voices (sherpa-onnx models).
///
/// Archives are the official sherpa-onnx TTS model releases. Each extracts to
/// a directory named [dirName] containing the .onnx model, tokens.txt, and
/// espeak-ng-data/ (Kokoro additionally ships voices.bin).
library;

/// Sentinel voice id meaning "use the platform TTS engine" (flutter_tts).
const String kSystemVoiceId = 'system';

class NeuralVoice {
  final String id;
  final String label;
  final String desc;
  final String archiveUrl;

  /// Top-level directory name inside the archive (and on disk once installed).
  final String dirName;

  /// Approximate download size, shown in the settings UI.
  final int sizeMB;

  /// Speaker id within the model (Kokoro models are multi-speaker).
  final int sid;

  const NeuralVoice({
    required this.id,
    required this.label,
    required this.desc,
    required this.archiveUrl,
    required this.dirName,
    required this.sizeMB,
    this.sid = 0,
  });
}

const String _releaseBase =
    'https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models';

const List<NeuralVoice> kNeuralVoices = [
  NeuralVoice(
    id: 'piper-amy',
    label: 'Amy',
    desc: 'Warm American voice',
    archiveUrl: '$_releaseBase/vits-piper-en_US-amy-medium.tar.bz2',
    dirName: 'vits-piper-en_US-amy-medium',
    sizeMB: 75,
  ),
  NeuralVoice(
    id: 'piper-lessac',
    label: 'Lessac',
    desc: 'Clear, balanced American voice',
    archiveUrl: '$_releaseBase/vits-piper-en_US-lessac-medium.tar.bz2',
    dirName: 'vits-piper-en_US-lessac-medium',
    sizeMB: 75,
  ),
  NeuralVoice(
    id: 'piper-alba',
    label: 'Alba',
    desc: 'Soft British voice',
    archiveUrl: '$_releaseBase/vits-piper-en_GB-alba-medium.tar.bz2',
    dirName: 'vits-piper-en_GB-alba-medium',
    sizeMB: 75,
  ),
  NeuralVoice(
    id: 'kokoro',
    label: 'Kokoro',
    desc: 'Most natural · slower on older phones',
    archiveUrl: '$_releaseBase/kokoro-en-v0_19.tar.bz2',
    dirName: 'kokoro-en-v0_19',
    sizeMB: 310,
  ),
];

NeuralVoice? neuralVoiceById(String id) {
  for (final v in kNeuralVoices) {
    if (v.id == id) return v;
  }
  return null;
}
