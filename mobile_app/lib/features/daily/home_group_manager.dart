import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class HomeGroupMeeting {
  final String id;
  final String name;
  final String dayName;
  final String timeString;
  final String location;
  final bool reminderEnabled;

  HomeGroupMeeting({
    required this.id,
    required this.name,
    required this.dayName,
    required this.timeString,
    required this.location,
    this.reminderEnabled = true,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'dayName': dayName,
        'timeString': timeString,
        'location': location,
        'reminderEnabled': reminderEnabled,
      };

  factory HomeGroupMeeting.fromJson(Map<String, dynamic> json) => HomeGroupMeeting(
        id: json['id'] as String? ?? '',
        name: json['name'] as String? ?? 'Home Group Meeting',
        dayName: json['dayName'] as String? ?? 'Sunday',
        timeString: json['timeString'] as String? ?? '7:00 PM',
        location: json['location'] as String? ?? '',
        reminderEnabled: json['reminderEnabled'] as bool? ?? true,
      );
}

class HomeGroupManager {
  static const String _kHomeGroupKey = 'home_group_meeting_v1';

  static Future<void> saveHomeGroup(SharedPreferences prefs, HomeGroupMeeting meeting) async {
    await prefs.setString(_kHomeGroupKey, jsonEncode(meeting.toJson()));
  }

  static HomeGroupMeeting? getHomeGroup(SharedPreferences prefs) {
    final raw = prefs.getString(_kHomeGroupKey);
    if (raw == null || raw.isEmpty) return null;
    try {
      return HomeGroupMeeting.fromJson(jsonDecode(raw));
    } catch (_) {
      return null;
    }
  }

  static Future<void> clearHomeGroup(SharedPreferences prefs) async {
    await prefs.remove(_kHomeGroupKey);
  }
}
