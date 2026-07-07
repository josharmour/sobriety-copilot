/// Models for meeting search (geocode + meetings) and server health.
///
/// Wire shapes (from the backend API contract):
/// - GET /api/geocode?q=  -> {"lat":num,"lng":num,"label":str}
/// - GET /api/meetings    -> {"meetings":[Meeting...],"total_in_radius":int,
///                            "feeds_total":int,"feeds_with_data":int}
/// - GET /api/health      -> {"status":"ok|degraded","model":str,
///                            "indexed_chunks":int|null, ...}
library;

/// Helper: coerce a dynamic JSON value into a double, tolerating ints,
/// numeric strings, and nulls.
double _asDouble(dynamic v, [double fallback = 0]) {
  if (v == null) return fallback;
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v) ?? fallback;
  return fallback;
}

/// Helper: coerce a dynamic JSON value into an int, tolerating doubles,
/// numeric strings, and nulls.
int _asInt(dynamic v, [int fallback = 0]) {
  if (v == null) return fallback;
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? fallback;
  return fallback;
}

/// Helper: coerce a dynamic JSON value into a nullable int.
int? _asIntOrNull(dynamic v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v);
  return null;
}

/// Helper: coerce a dynamic JSON value into a non-null String.
String _asString(dynamic v, [String fallback = '']) {
  if (v == null) return fallback;
  if (v is String) return v;
  return v.toString();
}

/// Helper: coerce a dynamic JSON value into a nullable String.
String? _asStringOrNull(dynamic v) {
  if (v == null) return null;
  if (v is String) return v;
  return v.toString();
}

/// Helper: coerce a dynamic JSON value into a bool, tolerating
/// truthy ints/strings.
bool _asBool(dynamic v, [bool fallback = false]) {
  if (v == null) return fallback;
  if (v is bool) return v;
  if (v is num) return v != 0;
  if (v is String) {
    final s = v.trim().toLowerCase();
    return s == 'true' || s == '1' || s == 'yes';
  }
  return fallback;
}

/// Helper: coerce a dynamic JSON value into a `List<String>`.
List<String> _asStringList(dynamic v) {
  if (v == null) return const [];
  if (v is List) {
    return v.map((e) => _asString(e)).where((s) => s.isNotEmpty).toList();
  }
  if (v is String && v.isNotEmpty) return [v];
  return const [];
}

/// /api/geocode result.
class GeoResult {
  final double lat;
  final double lng;
  final String label;

  const GeoResult({required this.lat, required this.lng, required this.label});

  factory GeoResult.fromJson(Map<String, dynamic> json) {
    return GeoResult(
      lat: _asDouble(json['lat']),
      lng: _asDouble(json['lng']),
      label: _asString(json['label']),
    );
  }
}

/// One meeting from /api/meetings -> "meetings"[].
class Meeting {
  final String name;
  final String group;
  final int? day; // 0=Sun..6=Sat (nullable)
  final String? dayName; // server "day_name"
  final String time; // "HH:MM" 24h, may be ""
  final String timeFormatted; // "7:00 pm"
  final String address; // server "formatted_address"
  final List<String> types;
  final String url; // group/meeting url
  final String website;
  final String conferenceUrl; // online join link (may be "")
  final String conferenceUrlNotes; // e.g. plain-text passcode instructions
  final String conferencePhone;
  final double lat;
  final double lng;
  final double distanceMi; // server "distance_mi"
  final bool isOnline; // server "is_online"/"online"
  final bool isInperson; // server "is_inperson"
  final String fellowship; // "AA" | "NA" | other fellowship names
  final String region;
  final String location; // venue name
  // Online-directory extras (/api/meetings/online); null/false elsewhere.
  final int? startsInMinutes; // minutes until next occurrence (may be < 0)
  final bool isLiveNow; // started within the live window

  const Meeting({
    required this.name,
    required this.group,
    required this.day,
    required this.dayName,
    required this.time,
    required this.timeFormatted,
    required this.address,
    required this.types,
    required this.url,
    required this.website,
    required this.conferenceUrl,
    this.conferenceUrlNotes = '',
    required this.conferencePhone,
    required this.lat,
    required this.lng,
    required this.distanceMi,
    required this.isOnline,
    required this.isInperson,
    required this.fellowship,
    required this.region,
    required this.location,
    this.startsInMinutes,
    this.isLiveNow = false,
  });

  factory Meeting.fromJson(Map<String, dynamic> json) {
    return Meeting(
      name: _asString(json['name']),
      group: _asString(json['group']),
      day: _asIntOrNull(json['day']),
      dayName: _asStringOrNull(json['day_name']),
      time: _asString(json['time']),
      timeFormatted: _asString(json['time_formatted']),
      address: _asString(json['formatted_address']),
      types: _asStringList(json['types']),
      url: _asString(json['url']),
      website: _asString(json['website']),
      conferenceUrl: _asString(json['conference_url']),
      conferenceUrlNotes: _asString(json['conference_url_notes']),
      conferencePhone: _asString(json['conference_phone']),
      lat: _asDouble(json['lat']),
      lng: _asDouble(json['lng']),
      distanceMi: _asDouble(json['distance_mi']),
      // Backend may send either "is_online" or "online".
      isOnline: _asBool(json['is_online']) || _asBool(json['online']),
      isInperson: _asBool(json['is_inperson']),
      fellowship: _asString(json['fellowship']),
      region: _asString(json['region']),
      location: _asString(json['location']),
      startsInMinutes: _asIntOrNull(json['starts_in_minutes']),
      isLiveNow: _asBool(json['is_live_now']),
    );
  }
}

/// Full /api/meetings response envelope.
class MeetingSearchResult {
  final List<Meeting> meetings;
  final int totalInRadius; // "total_in_radius"
  final int feedsTotal; // "feeds_total"
  final int feedsWithData; // "feeds_with_data"

  const MeetingSearchResult({
    required this.meetings,
    required this.totalInRadius,
    required this.feedsTotal,
    required this.feedsWithData,
  });

  factory MeetingSearchResult.fromJson(Map<String, dynamic> json) {
    final raw = json['meetings'];
    final meetings = <Meeting>[];
    if (raw is List) {
      for (final item in raw) {
        if (item is Map<String, dynamic>) {
          meetings.add(Meeting.fromJson(item));
        } else if (item is Map) {
          meetings.add(Meeting.fromJson(Map<String, dynamic>.from(item)));
        }
      }
    }
    return MeetingSearchResult(
      meetings: meetings,
      // The online directory reports "total"; the geo search
      // "total_in_radius".
      totalInRadius: _asInt(json['total_in_radius'], _asInt(json['total'])),
      feedsTotal: _asInt(json['feeds_total']),
      feedsWithData: _asInt(json['feeds_with_data']),
    );
  }
}

/// /api/health response (subset we use).
class HealthStatus {
  final String status; // "ok" | "degraded"
  final String model;
  final int? indexedChunks;

  const HealthStatus({
    required this.status,
    required this.model,
    this.indexedChunks,
  });

  factory HealthStatus.fromJson(Map<String, dynamic> json) {
    return HealthStatus(
      status: _asString(json['status']),
      model: _asString(json['model']),
      indexedChunks: _asIntOrNull(json['indexed_chunks']),
    );
  }

  bool get isOk => status == 'ok';
}
