import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sobriety_copilot_mobile/data/repositories/library_models.dart';

class LibraryRepository {
  final http.Client client;
  final SharedPreferences prefs;
  final String Function() baseUrl;

  LibraryRepository({
    required this.client,
    required this.prefs,
    required this.baseUrl,
  });

  int get localPackVersion => 0;
  int get localPackDocCount => 0;

  Future<bool> get isPackInstalled async => false;

  Future<Map<String, dynamic>?> checkLatestPack() async => null;

  Future<void> downloadAndInstallPack(int version, String expectedSha256, {Function(double)? onProgress}) async {
    throw UnsupportedError('Offline packs are not supported on the web.');
  }

  Future<void> closeDb() async {}

  Future<List<OfflineBookIndex>> getBooks() async => [];

  Future<Map<String, dynamic>?> getManifest(String docId) async => null;

  Future<List<OfflineSearchResult>> search(String query) async => [];

  /// No offline vectors on web.
  Future<({String blob, String idx, String meta})?> vectorFiles() async => null;

  Future<OfflineSearchResult?> getBlock(String docId, String blockId) async =>
      null;
}
