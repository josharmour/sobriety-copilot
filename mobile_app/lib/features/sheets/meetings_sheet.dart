import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/data/models/meeting_models.dart';
import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';

/// Find-a-meeting bottom sheet.
///
/// Mirrors the web app's meeting sheet (`static/index.html`):
/// location input -> `/api/geocode`, "use my location" -> `geolocator`, then
/// `/api/meetings`. Fellowship + attendance filters trigger a server re-fetch
/// (they change the payload); day-range and time-of-day filters are applied
/// client-side. Results are de-duped per occurrence, or grouped by meeting for
/// the "This week" / "Any day" views.
class MeetingsSheet extends ConsumerStatefulWidget {
  const MeetingsSheet({super.key});

  @override
  ConsumerState<MeetingsSheet> createState() => _MeetingsSheetState();
}

const List<String> _dayNames = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
];
const List<String> _dayShort = [
  'Sun',
  'Mon',
  'Tue',
  'Wed',
  'Thu',
  'Fri',
  'Sat',
];

/// A single (day, time) occurrence of a recurring meeting.
class _Occ {
  final int? day;
  final String time;
  const _Occ(this.day, this.time);
}

/// A meeting grouped with all of its weekly occurrences.
class _MeetingGroup {
  final Meeting rep;
  final List<_Occ> occurrences;
  const _MeetingGroup(this.rep, this.occurrences);
}

class _MeetingsSheetState extends ConsumerState<MeetingsSheet> {
  final TextEditingController _locationController = TextEditingController();

  double? _lat;
  double? _lng;
  String _locationLabel = '';
  bool _locationIsPlaceholder = false;
  bool _locating = false;

  // Mode: geographic search vs the location-agnostic online directory.
  String _mode = 'nearby'; // nearby | online

  // Filters.
  String _fellowship = 'all'; // all | aa | na | recovery dharma | cma
  String _attendance = 'inperson'; // inperson | online | all
  String _range = 'today'; // today | tonight | tomorrow | week | any
  String _timeOfDay = 'any'; // any | morning | afternoon | evening | late
  int _radiusMi = 30; // persisted across sessions

  static const String _radiusPrefsKey = 'meeting_radius_mi';
  static const String _zoomAckPrefsKey = 'zoom_anonymity_ack_v1';
  static const List<int> _radiusOptions = [15, 30, 60, 100, 200];

  bool _loading = false;
  String? _error;
  MeetingSearchResult? _lastResults;
  MeetingSearchResult? _onlineResults;

  @override
  void initState() {
    super.initState();
    final stored =
        ref.read(sharedPreferencesProvider).getInt(_radiusPrefsKey);
    if (stored != null && _radiusOptions.contains(stored)) {
      _radiusMi = stored;
    }
  }

  @override
  void dispose() {
    _locationController.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Time helpers (mirror the web app).
  // ---------------------------------------------------------------------------

  String _formatTime(String t) {
    if (t.length < 4) return '';
    final parts = t.split(':');
    if (parts.length < 2) return '';
    final h = int.tryParse(parts[0]);
    final mm = parts[1];
    if (h == null) return '';
    final ampm = h >= 12 ? 'PM' : 'AM';
    final h12 = ((h + 11) % 12) + 1;
    return '$h12:$mm $ampm';
  }

  int _timeAsMinutes(String t) {
    if (t.length < 4) return -1;
    final parts = t.split(':');
    if (parts.length < 2) return -1;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null) return -1;
    return h * 60 + m;
  }

  String? _timeOfDayBucket(String t) {
    final min = _timeAsMinutes(t);
    if (min < 0) return null;
    if (min >= 5 * 60 && min < 12 * 60) return 'morning';
    if (min >= 12 * 60 && min < 17 * 60) return 'afternoon';
    if (min >= 17 * 60 && min < 21 * 60) return 'evening';
    return 'late';
  }

  List<Meeting> _filterByTimeOfDay(List<Meeting> meetings, String tod) {
    if (tod == 'any') return meetings;
    return meetings.where((m) => _timeOfDayBucket(m.time) == tod).toList();
  }

  List<Meeting> _filterByRange(List<Meeting> meetings, String range) {
    if (range == 'any' || range == 'week') return meetings;
    final now = DateTime.now();
    final today = now.weekday % 7; // Dart Mon=1..Sun=7 -> JS Sun=0..Sat=6
    final tomorrow = (today + 1) % 7;
    final nowMin = now.hour * 60 + now.minute;
    if (range == 'today') {
      return meetings
          .where((m) => m.day == today && _timeAsMinutes(m.time) >= nowMin)
          .toList();
    }
    if (range == 'tonight') {
      if (now.hour < 4) {
        return meetings
            .where((m) =>
                m.day == today &&
                _timeAsMinutes(m.time) >= nowMin &&
                _timeAsMinutes(m.time) < 4 * 60)
            .toList();
      }
      final floor = nowMin > 18 * 60 ? nowMin : 18 * 60;
      return meetings
          .where((m) => m.day == today && _timeAsMinutes(m.time) >= floor)
          .toList();
    }
    if (range == 'tomorrow') {
      return meetings.where((m) => m.day == tomorrow).toList();
    }
    return meetings;
  }

  String _dedupeKey(Meeting m) {
    final coords =
        '${m.lat.toStringAsFixed(3)},${m.lng.toStringAsFixed(3)}';
    if (m.group.isNotEmpty) {
      return 'g:${m.group.toLowerCase()}|$coords';
    }
    return '${m.name}|${m.lat.toStringAsFixed(4)},${m.lng.toStringAsFixed(4)}';
  }

  List<_MeetingGroup> _groupOccurrences(List<Meeting> meetings) {
    final order = <String>[];
    final groups = <String, _MeetingGroup>{};
    for (final m in meetings) {
      final key = _dedupeKey(m);
      if (!groups.containsKey(key)) {
        order.add(key);
        groups[key] = _MeetingGroup(m, <_Occ>[]);
      }
      groups[key]!.occurrences.add(_Occ(m.day, m.time));
    }
    return [for (final k in order) groups[k]!];
  }

  // ---------------------------------------------------------------------------
  // Networking.
  // ---------------------------------------------------------------------------

  void _setLocationLabel(String text, {bool placeholder = false}) {
    setState(() {
      _locationLabel = text;
      _locationIsPlaceholder = placeholder;
    });
  }

  Future<void> _setLocationFromQuery(String q) async {
    setState(() => _locating = true);
    _setLocationLabel('Looking up $q…', placeholder: true);
    try {
      final geo = await ref.read(meetingRepositoryProvider).geocode(q);
      setState(() {
        _lat = geo.lat;
        _lng = geo.lng;
      });
      _setLocationLabel(geo.label);
      _locationController.clear();
      await _fetchAndRender();
    } catch (_) {
      _setLocationLabel("Couldn't find $q — try a ZIP code", placeholder: true);
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _setLocationFromGeolocation() async {
    setState(() => _locating = true);
    _setLocationLabel('Getting your location…', placeholder: true);
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        _setLocationLabel('Location off — type a ZIP code above',
            placeholder: true);
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        _setLocationLabel('Location denied — type a ZIP code above',
            placeholder: true);
        if (permission == LocationPermission.deniedForever && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content:
                  const Text('Location is turned off for Sobriety Copilot.'),
              action: SnackBarAction(
                label: 'Open Settings',
                onPressed: () => Geolocator.openAppSettings(),
              ),
            ),
          );
        }
        return;
      }
      final pos = await Geolocator.getCurrentPosition(
        locationSettings:
            const LocationSettings(accuracy: LocationAccuracy.low),
      ).timeout(const Duration(seconds: 8));
      setState(() {
        _lat = pos.latitude;
        _lng = pos.longitude;
      });
      _setLocationLabel('Your current location');
      await _fetchAndRender();
    } catch (_) {
      _setLocationLabel("Couldn't get location — type a ZIP code above",
          placeholder: true);
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _fetchAndRender() async {
    if (_lat == null || _lng == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await ref
          .read(meetingRepositoryProvider)
          .meetings(
            lat: _lat!,
            lng: _lng!,
            radiusMi: _radiusMi.toDouble(),
            max: 100,
            attendance: _attendance == 'all' ? null : _attendance,
            fellowship: _fellowship == 'all' ? null : _fellowship,
          )
          .timeout(const Duration(seconds: 25));
      if (!mounted) return;
      setState(() => _lastResults = result);
    } on TimeoutException {
      if (!mounted) return;
      setState(() => _error = 'The meeting service timed out. Please retry.');
    } catch (e) {
      if (!mounted) return;
      setState(
          () => _error = "Couldn't reach the meeting service. ${_clean(e)}");
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _fetchOnline() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final fellowship =
          (_fellowship == 'aa' || _fellowship == 'na') ? _fellowship : null;
      final result = await ref
          .read(meetingRepositoryProvider)
          .onlineMeetings(fellowship: fellowship, max: 100)
          .timeout(const Duration(seconds: 25));
      if (!mounted) return;
      setState(() => _onlineResults = result);
    } on TimeoutException {
      if (!mounted) return;
      setState(() => _error = 'The meeting service timed out. Please retry.');
    } catch (e) {
      if (!mounted) return;
      setState(
          () => _error = "Couldn't reach the meeting service. ${_clean(e)}");
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _clean(Object e) {
    final s = e.toString();
    return s.startsWith('Exception: ') ? s.substring(11) : s;
  }

  // ---------------------------------------------------------------------------
  // External links.
  // ---------------------------------------------------------------------------

  Future<void> _open(String url) async {
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Couldn't open link")),
        );
      }
    }
  }

  String _mapsQuery(String query) =>
      'https://www.google.com/maps/search/?api=1&query=${Uri.encodeComponent(query)}';

  /// Join an online meeting: a one-time anonymity note (Zoom shows your
  /// account name to the room), passcode notes with a copy button when the
  /// feed provides them, then hand off to the external app/browser.
  Future<void> _joinOnline(Meeting m) async {
    final prefs = ref.read(sharedPreferencesProvider);
    final acked = prefs.getBool(_zoomAckPrefsKey) ?? false;
    final notes = m.conferenceUrlNotes.trim();

    if (!acked || notes.isNotEmpty) {
      final proceed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Before you join'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!acked) ...[
                const Text(
                  'Video apps show your account name and photo to everyone '
                  'in the meeting. For anonymity, consider renaming yourself '
                  'to a first name and last initial (e.g. "Sam B.") and '
                  'joining with your camera off.',
                ),
                const SizedBox(height: AppSpacing.sm),
              ],
              if (notes.isNotEmpty) ...[
                Text(
                  'Join notes from the group:',
                  style: Theme.of(dialogContext)
                      .textTheme
                      .bodySmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: AppSpacing.xs),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        notes,
                        style: Theme.of(dialogContext).textTheme.bodySmall,
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.copy, size: 16),
                      tooltip: 'Copy',
                      onPressed: () {
                        Clipboard.setData(ClipboardData(text: notes));
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Copied')),
                        );
                      },
                    ),
                  ],
                ),
              ],
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('Join meeting'),
            ),
          ],
        ),
      );
      if (proceed != true) return;
      if (!acked) await prefs.setBool(_zoomAckPrefsKey, true);
    }
    await _open(m.conferenceUrl);
  }

  Future<void> _reportListing(Meeting m) async {
    final desc = 'Meeting listing report: "${m.name}" '
        '(${m.fellowship}, ${m.dayName ?? ''} ${m.time}, '
        'source data may be stale or the link may be broken). '
        'conference_url=${m.conferenceUrl}';
    try {
      await ref.read(meetingRepositoryProvider).report(desc);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Thanks — reported.')),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Couldn't send the report.")),
        );
      }
    }
  }

  Future<void> _reportCoverageGap() async {
    final where = _locationLabel.isNotEmpty ? _locationLabel : 'unknown area';
    try {
      await ref
          .read(meetingRepositoryProvider)
          .report('Meeting coverage request: no useful results near "$where" '
              '(radius $_radiusMi mi, fellowship $_fellowship).');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Thanks — we'll look for feeds covering your area."),
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Couldn't send the request.")),
        );
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Build.
  // ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasLocation = _lat != null && _lng != null;

    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom,
        ),
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.of(context).size.height * 0.9,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.xl,
                  AppSpacing.lg,
                  AppSpacing.xl,
                  AppSpacing.sm,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [

                    Text(
                      'Find a meeting',
                      style: theme.textTheme.titleLarge,
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      'In-person, online, and across many fellowships.',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.textTheme.bodySmall?.color
                            ?.withValues(alpha: 0.7),
                      ),
                    ),
                  ],
                ),
              ),
              _buildModeSwitch(theme),
              _buildSearchControls(theme),
              const Divider(height: 1),
              Flexible(
                child: _mode == 'online'
                    ? (_loading
                        ? _buildLoading(theme)
                        : _error != null
                            ? _buildError(theme)
                            : _buildOnlineResults(theme))
                    : !hasLocation
                        ? _buildPrompt(theme)
                        : _loading
                            ? _buildLoading(theme)
                            : _error != null
                                ? _buildError(theme)
                                : _buildResults(theme),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildModeSwitch(ThemeData theme) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.xl,
        0,
        AppSpacing.xl,
        AppSpacing.md,
      ),
      child: SegmentedButton<String>(
        segments: const [
          ButtonSegment(
            value: 'nearby',
            label: Text('Nearby'),
            icon: Icon(Icons.place_outlined, size: 16),
          ),
          ButtonSegment(
            value: 'online',
            label: Text('Online now'),
            icon: Icon(Icons.videocam_outlined, size: 16),
          ),
        ],
        selected: {_mode},
        showSelectedIcon: false,
        style: const ButtonStyle(
          visualDensity: VisualDensity.compact,
        ),
        onSelectionChanged: (sel) {
          final next = sel.first;
          if (next == _mode) return;
          setState(() => _mode = next);
          if (next == 'online' && _onlineResults == null && !_loading) {
            _fetchOnline();
          }
        },
      ),
    );
  }

  Widget _buildSearchControls(ThemeData theme) {
    final online = _mode == 'online';
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.xl,
        0,
        AppSpacing.xl,
        AppSpacing.md,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!online) ...[
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _locationController,
                    textInputAction: TextInputAction.search,
                    onSubmitted: (v) {
                      final q = v.trim();
                      if (q.isNotEmpty) _setLocationFromQuery(q);
                    },
                    decoration: const InputDecoration(
                      hintText: 'ZIP code or city',
                      prefixIcon: Icon(Icons.search),
                      isDense: true,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                IconButton.filledTonal(
                  onPressed: _locating ? null : _setLocationFromGeolocation,
                  tooltip: 'Use my location',
                  icon: _locating
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.my_location),
                ),
              ],
            ),
            if (_locationLabel.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Opacity(
                opacity: _locationIsPlaceholder ? 0.7 : 1,
                child: Row(
                  children: [
                    const Icon(Icons.place_outlined,
                        size: 14, color: AppColors.accent),
                    const SizedBox(width: AppSpacing.xs),
                    Expanded(
                      child: Text(
                        _locationLabel,
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.md),
          ],
          _filterRow(
            options: online
                ? const {'all': 'AA & NA', 'aa': 'AA', 'na': 'NA'}
                : const {
                    'all': 'All',
                    'aa': 'AA',
                    'na': 'NA',
                    'recovery dharma': 'Dharma',
                    'cma': 'CMA',
                  },
            selected: (online &&
                    _fellowship != 'aa' &&
                    _fellowship != 'na')
                ? 'all'
                : _fellowship,
            onSelected: (v) {
              setState(() => _fellowship = v);
              if (online) {
                _fetchOnline();
              } else {
                _fetchAndRender();
              }
            },
          ),
          if (!online) ...[
            const SizedBox(height: AppSpacing.sm),
            _filterRow(
              options: const {
                'inperson': 'In-person',
                'online': 'Online',
                'all': 'All',
              },
              selected: _attendance,
              onSelected: (v) {
                setState(() => _attendance = v);
                _fetchAndRender();
              },
            ),
            const SizedBox(height: AppSpacing.sm),
            _filterRow(
              options: const {
                'today': 'Today',
                'tonight': 'Tonight',
                'tomorrow': 'Tomorrow',
                'week': 'This week',
                'any': 'Any day',
              },
              selected: _range,
              onSelected: (v) => setState(() => _range = v),
            ),
            const SizedBox(height: AppSpacing.sm),
            _filterRow(
              options: const {
                'any': 'Any time',
                'morning': 'Morning',
                'afternoon': 'Afternoon',
                'evening': 'Evening',
                'late': 'Late night',
              },
              selected: _timeOfDay,
              onSelected: (v) => setState(() => _timeOfDay = v),
            ),
            const SizedBox(height: AppSpacing.sm),
            _filterRow(
              options: {
                for (final r in _radiusOptions) '$r': '$r mi',
              },
              selected: '$_radiusMi',
              onSelected: (v) {
                final r = int.tryParse(v);
                if (r == null) return;
                setState(() => _radiusMi = r);
                ref
                    .read(sharedPreferencesProvider)
                    .setInt(_radiusPrefsKey, r);
                _fetchAndRender();
              },
            ),
          ],
        ],
      ),
    );
  }

  Widget _filterRow({
    required Map<String, String> options,
    required String selected,
    required ValueChanged<String> onSelected,
  }) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final entry in options.entries)
            Padding(
              padding: const EdgeInsets.only(right: AppSpacing.sm),
              child: ChoiceChip(
                label: Text(entry.value),
                selected: selected == entry.key,
                onSelected: (_) {
                  if (selected != entry.key) onSelected(entry.key);
                },
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildPrompt(ThemeData theme) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.place_outlined,
                size: 40, color: AppColors.accent),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Enter a ZIP code or use your location to find meetings nearby.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.lg),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              alignment: WrapAlignment.center,
              children: [
                OutlinedButton.icon(
                  onPressed: () => _open(_mapsQuery('AA meetings near me')),
                  icon: const Icon(Icons.public, size: 16),
                  label: const Text('AA online'),
                ),
                OutlinedButton.icon(
                  onPressed: () =>
                      _open('https://www.na.org/meetingsearch/'),
                  icon: const Icon(Icons.public, size: 16),
                  label: const Text('NA meetings'),
                ),
                OutlinedButton.icon(
                  onPressed: () => _open(
                      'https://meetings.smartrecovery.org/meetings/'),
                  icon: const Icon(Icons.public, size: 16),
                  label: const Text('SMART Recovery'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildLoading(ThemeData theme) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: AppSpacing.lg),
            Text(
              'Searching nearby intergroup feeds…\n(first call can take 5–10 s)',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildError(ThemeData theme) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 36, color: AppColors.error),
            const SizedBox(height: AppSpacing.md),
            Text(
              _error ?? 'Something went wrong.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.lg),
            Wrap(
              spacing: AppSpacing.sm,
              alignment: WrapAlignment.center,
              children: [
                FilledButton(
                  onPressed: _fetchAndRender,
                  child: const Text('Retry'),
                ),
                OutlinedButton(
                  onPressed: () => _open(_mapsQuery('AA meeting')),
                  child: const Text('Open in Maps'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildResults(ThemeData theme) {
    final data = _lastResults;
    if (data == null) {
      return _buildPrompt(theme);
    }

    final grouped = _range == 'week' || _range == 'any';
    final List<Widget> cards = [];
    int count;

    if (grouped) {
      final filtered = _filterByTimeOfDay(data.meetings, _timeOfDay);
      final groups = _groupOccurrences(filtered);
      count = groups.length;
      for (final g in groups) {
        cards.add(_groupCard(theme, g));
      }
    } else {
      final filtered = _filterByTimeOfDay(
        _filterByRange(data.meetings, _range),
        _timeOfDay,
      );
      final seen = <String>{};
      final display = <Meeting>[];
      for (final m in filtered) {
        final k = '${_dedupeKey(m)}|${m.day}|${m.time}';
        if (seen.add(k)) display.add(m);
      }
      count = display.length;
      for (final m in display) {
        cards.add(_meetingCard(theme, m));
      }
    }

    final countLabel = count > 0
        ? '$count ${grouped ? 'groups' : 'meetings'} within $_radiusMi mi'
        : 'No meetings match';

    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.md,
        AppSpacing.lg,
        AppSpacing.xl,
      ),
      children: [
        Padding(
          padding: const EdgeInsets.only(
            left: AppSpacing.xs,
            bottom: AppSpacing.sm,
          ),
          child: Text(
            countLabel,
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.textTheme.bodySmall?.color,
            ),
          ),
        ),
        if (count == 0)
          _emptyCard(theme)
        else
          ...cards,
        const SizedBox(height: AppSpacing.lg),
        Center(
          child: Column(
            children: [
              Text(
                "Coverage from a curated set of intergroup feeds.",
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
                  color:
                      theme.textTheme.bodySmall?.color?.withValues(alpha: 0.6),
                ),
              ),
              TextButton(
                onPressed: _reportCoverageGap,
                child: const Text("Don't see meetings near you? Tell us"),
              ),
            ],
          ),
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Online directory.
  // ---------------------------------------------------------------------------

  String _startsLabel(Meeting m) {
    if (m.isLiveNow) return 'LIVE';
    final mins = m.startsInMinutes;
    if (mins == null) return '';
    if (mins < 60) return 'in $mins min';
    if (mins < 24 * 60) {
      final h = mins ~/ 60;
      return 'in $h h${h == 1 ? '' : ''}';
    }
    return m.dayName ?? '';
  }

  Widget _buildOnlineResults(ThemeData theme) {
    final data = _onlineResults;
    if (data == null) {
      return _buildLoading(theme);
    }
    final meetings = data.meetings;
    final liveCount = meetings.where((m) => m.isLiveNow).length;

    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.md,
        AppSpacing.lg,
        AppSpacing.xl,
      ),
      children: [
        Padding(
          padding: const EdgeInsets.only(
            left: AppSpacing.xs,
            bottom: AppSpacing.sm,
          ),
          child: Text(
            meetings.isEmpty
                ? 'No online meetings found'
                : '${data.totalInRadius} online meetings worldwide'
                    '${liveCount > 0 ? ' · $liveCount live right now' : ''}',
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.textTheme.bodySmall?.color,
            ),
          ),
        ),
        if (meetings.isEmpty)
          _emptyCard(theme)
        else
          ...meetings.map((m) => _onlineCard(theme, m)),
        const SizedBox(height: AppSpacing.lg),
        Center(
          child: Text(
            'Directories: Online Intergroup of A.A. and Virtual NA.\n'
            'Times shown in each meeting\'s local schedule.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.textTheme.bodySmall?.color?.withValues(alpha: 0.6),
            ),
          ),
        ),
      ],
    );
  }

  Widget _onlineCard(ThemeData theme, Meeting m) {
    final startsLabel = _startsLabel(m);
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    _whenLine(m),
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (startsLabel.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: m.isLiveNow
                          ? Colors.green.withValues(alpha: 0.15)
                          : AppColors.accentSoft,
                      border: Border.all(
                        color: m.isLiveNow ? Colors.green : AppColors.accent,
                      ),
                      borderRadius: BorderRadius.circular(AppSpacing.sm),
                    ),
                    child: Text(
                      startsLabel,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: m.isLiveNow ? Colors.green : AppColors.accent,
                      ),
                    ),
                  ),
                PopupMenuButton<String>(
                  padding: EdgeInsets.zero,
                  iconSize: 16,
                  onSelected: (v) {
                    if (v == 'report') _reportListing(m);
                  },
                  itemBuilder: (context) => const [
                    PopupMenuItem(
                      value: 'report',
                      child: Text('Report this listing'),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _fellowshipPill(m),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    m.name.isEmpty ? 'Meeting' : m.name,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            if (m.region.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  m.region,
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontSize: 11,
                    color: theme.textTheme.bodySmall?.color
                        ?.withValues(alpha: 0.7),
                  ),
                ),
              ),
            if (_tags(m).isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                children: _tags(m),
              ),
            ],
            if (_actions(m).isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: _actions(m),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _emptyCard(ThemeData theme) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          children: [
            Text(
              'No matches for this filter. Try a wider time range, a different '
              'ZIP, or the launchers above.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.md),
            OutlinedButton(
              onPressed: () => _open(_mapsQuery('AA meeting')),
              child: const Text('Search Google Maps instead'),
            ),
          ],
        ),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Cards.
  // ---------------------------------------------------------------------------

  Widget _fellowshipPill(Meeting m) {
    final fellow =
        (m.fellowship.isEmpty ? 'AA' : m.fellowship).toUpperCase();
    final isNa = fellow == 'NA';
    final color = isNa ? const Color(0xFFB4654A) : AppColors.accent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        fellow,
        style: TextStyle(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.5,
        ),
      ),
    );
  }

  String _whenLine(Meeting m) {
    final dn = m.dayName != null && m.dayName!.isNotEmpty
        ? m.dayName!
        : (m.day != null && m.day! >= 0 && m.day! < 7 ? _dayNames[m.day!] : '');
    final t =
        m.timeFormatted.isNotEmpty ? m.timeFormatted : _formatTime(m.time);
    if (dn.isNotEmpty && t.isNotEmpty) return '$dn · $t';
    return dn.isNotEmpty ? dn : t;
  }

  String _distanceLabel(Meeting m) {
    if (m.isInperson && m.distanceMi > 0) {
      return '${m.distanceMi.toStringAsFixed(1)} mi';
    }
    if (m.isOnline && !m.isInperson) return 'Online';
    if (m.distanceMi > 0) return '~${m.distanceMi.toStringAsFixed(1)} mi';
    return '';
  }

  List<Widget> _tags(Meeting m) {
    final out = <Widget>[];
    if (m.isOnline) out.add(_tag('Online', online: true));
    if (m.isInperson && m.isOnline) out.add(_tag('Hybrid'));
    const skip = {'ONL', 'ON', 'VM', 'TC'};
    for (final t in m.types.take(4)) {
      if (t.isEmpty || skip.contains(t.toUpperCase())) continue;
      out.add(_tag(t));
    }
    return out;
  }

  Widget _tag(String text, {bool online = false}) {
    final color = online ? AppColors.accent : null;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: online
            ? AppColors.accentSoft
            : Colors.grey.withValues(alpha: 0.12),
        border: online ? Border.all(color: AppColors.accent) : null,
        borderRadius: BorderRadius.circular(AppSpacing.sm),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 11,
          color: color,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }

  List<Widget> _actions(Meeting m) {
    final out = <Widget>[];
    final where = m.address.isNotEmpty ? m.address : m.location;
    if (m.isInperson && where.isNotEmpty) {
      out.add(_actionButton(
        'Navigate',
        Icons.directions_outlined,
        () => _open(_mapsQuery(where)),
      ));
    }
    if (m.conferenceUrl.isNotEmpty) {
      out.add(_actionButton(
        'Join online',
        Icons.videocam_outlined,
        () => _joinOnline(m),
      ));
    }
    if (m.conferenceUrl.isEmpty && m.conferencePhone.isNotEmpty) {
      out.add(_actionButton(
        'Dial in',
        Icons.phone_outlined,
        () => _open('tel:${m.conferencePhone}'),
      ));
    }
    if (m.url.isNotEmpty) {
      out.add(_actionButton(
        'Details',
        Icons.open_in_new,
        () => _open(m.url),
      ));
    }
    return out;
  }

  Widget _actionButton(String label, IconData icon, VoidCallback onTap) {
    return OutlinedButton.icon(
      onPressed: onTap,
      icon: Icon(icon, size: 14),
      label: Text(label),
      style: OutlinedButton.styleFrom(
        padding:
            const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 4),
        minimumSize: const Size(0, 32),
        textStyle: const TextStyle(fontSize: 12),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  Widget _meetingCard(ThemeData theme, Meeting m) {
    final where = m.address.isNotEmpty ? m.address : m.location;
    final hood = m.region;
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    _whenLine(m),
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (_distanceLabel(m).isNotEmpty)
                  Text(
                    _distanceLabel(m),
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: m.isOnline && !m.isInperson
                          ? AppColors.accent
                          : theme.textTheme.bodySmall?.color,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _fellowshipPill(m),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    m.name.isEmpty ? 'Meeting' : m.name,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            if (m.group.isNotEmpty && m.group != m.name)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  m.group,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(fontStyle: FontStyle.italic),
                ),
              ),
            if (where.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(where, style: theme.textTheme.bodySmall),
              ),
            if (hood.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  hood,
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontSize: 11,
                    color: theme.textTheme.bodySmall?.color
                        ?.withValues(alpha: 0.7),
                  ),
                ),
              ),
            if (_tags(m).isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: _tags(m)),
            ],
            if (_actions(m).isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.xs, children: _actions(m)),
            ],
          ],
        ),
      ),
    );
  }

  Widget _groupCard(ThemeData theme, _MeetingGroup g) {
    final m = g.rep;
    final occ = [...g.occurrences]
      ..sort((a, b) {
        final da = (a.day ?? 99).compareTo(b.day ?? 99);
        if (da != 0) return da;
        return _timeAsMinutes(a.time).compareTo(_timeAsMinutes(b.time));
      });
    final compact = occ
        .take(4)
        .map((o) {
          final ds = (o.day != null && o.day! >= 0 && o.day! < 7)
              ? _dayShort[o.day!]
              : '';
          return '$ds ${_formatTime(o.time)}'.trim();
        })
        .where((s) => s.isNotEmpty)
        .join(' · ');
    final more = occ.length > 4 ? ' +${occ.length - 4}' : '';
    final where = m.address.isNotEmpty ? m.address : m.location;

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    compact.isEmpty ? '—' : '$compact$more',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (_distanceLabel(m).isNotEmpty)
                  Text(_distanceLabel(m), style: theme.textTheme.bodySmall),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _fellowshipPill(m),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    m.name.isEmpty ? 'Meeting' : m.name,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            if (where.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(where, style: theme.textTheme.bodySmall),
              ),
            if (_tags(m).isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: _tags(m)),
            ],
            if (_actions(m).isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.xs, children: _actions(m)),
            ],
          ],
        ),
      ),
    );
  }
}
