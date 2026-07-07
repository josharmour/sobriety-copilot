import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image_picker/image_picker.dart';

Future<String?> scanTextFromCamera() async {
  final picker = ImagePicker();
  final file = await picker.pickImage(source: ImageSource.camera);
  if (file == null) return null;
  final recognizer = TextRecognizer();
  final recognized = await recognizer.processImage(
    InputImage.fromFilePath(file.path),
  );
  await recognizer.close();
  return recognized.text.replaceAll(RegExp(r'\s+'), ' ').trim();
}
