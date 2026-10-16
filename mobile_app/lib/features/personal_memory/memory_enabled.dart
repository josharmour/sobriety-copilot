// FR11 Wave C — memory-enabled master switch.
//
// A tiny persisted Notifier<bool> that gates ALL personal-memory UI injection
// (resume chip, "Personal memory on" hint) and the distiller cost. Lives in
// its own file so providers.dart stays free of feature-module imports beyond
// this one-liner indirection.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:sobriety_copilot_mobile/providers.dart';

/// SharedPreferences key for the memory-enabled toggle. Versioned per the
/// repo stability note: changing the schema means bumping the key.
const String kMemoryEnabledPrefsKey = 'personal_memory_enabled_v1';

class MemoryEnabledNotifier extends Notifier<bool> {
  @override
  bool build() {
    final raw =
        ref.read(sharedPreferencesProvider).getBool(kMemoryEnabledPrefsKey);
    // Default true: memory harms nothing and the feature must work out of
    // the box. Only an explicitly stored false turns it off.
    return raw ?? true;
  }

  Future<void> setEnabled(bool value) async {
    state = value;
    await ref
        .read(sharedPreferencesProvider)
        .setBool(kMemoryEnabledPrefsKey, value);
  }
}

/// Wired in providers.dart as `memoryEnabledProvider` so the chat notifier
/// can `ref.read` it with zero new imports beyond providers.dart itself.
abstract final class MemoryEnabledProvider {
  static final NotifierProvider<MemoryEnabledNotifier, bool> provider =
      NotifierProvider<MemoryEnabledNotifier, bool>(
    MemoryEnabledNotifier.new,
  );
}
