import 'package:flutter/foundation.dart';

// Native motion preferences are already supplied by MediaQuery.
ValueNotifier<bool> createMotionPreference() => ValueNotifier(false);
