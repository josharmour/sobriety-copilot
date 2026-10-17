import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:sobriety_copilot_mobile/providers.dart';
import 'package:sobriety_copilot_mobile/theme/tokens.dart';
import 'package:sobriety_copilot_mobile/widgets.dart';

const String _kSmsPrefsKey = 'sc_sms_subscription_v1';

class DailyBookOption {
  final String id;
  final String title;
  final String subtitle;
  final String badge;
  const DailyBookOption({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.badge,
  });
}

const List<DailyBookOption> kDailyBookOptions = [
  DailyBookOption(
    id: 'daily-reflections',
    title: 'Daily Reflections',
    subtitle: 'Full daily quote & reflection',
    badge: 'A.A.',
  ),
  DailyBookOption(
    id: 'twenty-four-hours-a-day',
    title: 'Twenty-Four Hours a Day',
    subtitle: 'Thought, Meditation & Prayer for the Day',
    badge: 'Hazelden / A.A.',
  ),
  DailyBookOption(
    id: 'just-for-today',
    title: 'Just for Today',
    subtitle: 'Daily meditation for recovery',
    badge: 'N.A.',
  ),
];

class TimezoneOption {
  final String iana;
  final String label;
  final String shortLabel;
  const TimezoneOption(this.iana, this.label, this.shortLabel);
}

const List<TimezoneOption> kTimezoneOptions = [
  TimezoneOption('America/Los_Angeles', 'Pacific Time (PT)', 'PT'),
  TimezoneOption('America/Denver', 'Mountain Time (MT)', 'MT'),
  TimezoneOption('America/Phoenix', 'Arizona Time (MST)', 'MST'),
  TimezoneOption('America/Chicago', 'Central Time (CT)', 'CT'),
  TimezoneOption('America/New_York', 'Eastern Time (ET)', 'ET'),
  TimezoneOption('America/Anchorage', 'Alaska Time (AKT)', 'AKT'),
  TimezoneOption('Pacific/Honolulu', 'Hawaii Time (HST)', 'HST'),
  TimezoneOption('America/Halifax', 'Atlantic Time (AT)', 'AT'),
  TimezoneOption('UTC', 'UTC', 'UTC'),
];

String _detectDefaultTimezone() {
  final tzName = DateTime.now().timeZoneName.toUpperCase();
  if (tzName.contains('EDT') || tzName.contains('EST')) {
    return 'America/New_York';
  }
  if (tzName.contains('CDT') || tzName.contains('CST')) {
    return 'America/Chicago';
  }
  if (tzName == 'MST') {
    return 'America/Phoenix';
  }
  if (tzName.contains('MDT')) {
    return 'America/Denver';
  }
  if (tzName.contains('AKDT') || tzName.contains('AKST')) {
    return 'America/Anchorage';
  }
  if (tzName.contains('HST')) {
    return 'Pacific/Honolulu';
  }
  final offsetHours = DateTime.now().timeZoneOffset.inHours;
  switch (offsetHours) {
    case -4:
      return 'America/New_York';
    case -5:
      return 'America/New_York';
    case -6:
      return 'America/Chicago';
    case -7:
      return 'America/Los_Angeles';
    case -8:
      return 'America/Los_Angeles';
    default:
      return 'America/Los_Angeles';
  }
}

String _shortTz(String iana) {
  for (final t in kTimezoneOptions) {
    if (t.iana == iana) return t.shortLabel;
  }
  return iana;
}

String _formatHhMm12h(String hhmm) {
  final parts = hhmm.split(':');
  if (parts.length != 2) return hhmm;
  final h = int.tryParse(parts[0]) ?? 7;
  final m = int.tryParse(parts[1]) ?? 0;
  final suffix = h < 12 ? 'AM' : 'PM';
  final h12 = h % 12 == 0 ? 12 : h % 12;
  final mStr = m.toString().padLeft(2, '0');
  return '$h12:$mStr $suffix';
}

/// Entry card shown in TodaySheet and SettingsSheet to open [SmsSubscriptionSheet].
class SmsSubscriptionTile extends ConsumerStatefulWidget {
  final bool asCard;
  const SmsSubscriptionTile({super.key, this.asCard = true});

  @override
  ConsumerState<SmsSubscriptionTile> createState() =>
      _SmsSubscriptionTileState();
}

class _SmsSubscriptionTileState extends ConsumerState<SmsSubscriptionTile> {
  bool _enabled = false;
  String _deliveryTime = '07:00';
  String _timezone = 'America/Los_Angeles';
  List<String> _books = const ['daily-reflections'];

  @override
  void initState() {
    super.initState();
    _loadLocal();
  }

  void _loadLocal() {
    final prefs = ref.read(sharedPreferencesProvider);
    final raw = prefs.getString(_kSmsPrefsKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final map = jsonDecode(raw) as Map<String, dynamic>;
      setState(() {
        _enabled = map['enabled'] == true;
        _deliveryTime = (map['delivery_time'] as String?) ?? '07:00';
        _timezone = (map['timezone'] as String?) ?? 'America/Los_Angeles';
        final b = map['books'];
        if (b is List && b.isNotEmpty) {
          _books = b.map((e) => e.toString()).toList();
        }
      });
    } catch (_) {}
  }

  Future<void> _openSheet() async {
    await showAppSheet(context, const SmsSubscriptionSheet());
    if (mounted) _loadLocal();
  }

  @override
  Widget build(BuildContext context) {
    final subtitle = _enabled
        ? 'Active · Daily at ${_formatHhMm12h(_deliveryTime)} ${_shortTz(_timezone)} (${_books.length} ${_books.length == 1 ? 'book' : 'books'})'
        : 'Get Daily Reflections, 24 Hours a Day, or Just for Today by text';

    final tile = ListTile(
      contentPadding: widget.asCard ? null : EdgeInsets.zero,
      leading: Icon(
        _enabled ? Icons.sms : Icons.sms_outlined,
        color: _enabled ? AppColors.accent : null,
      ),
      title: Text(
        _enabled ? 'Daily Reflection SMS — active' : 'Daily Reflection SMS',
      ),
      subtitle: Text(subtitle),
      trailing: const Icon(Icons.chevron_right),
      onTap: _openSheet,
    );

    if (widget.asCard) {
      return Card(child: tile);
    }
    return tile;
  }
}

/// Bottom sheet allowing users to subscribe to or manage scheduled daily
/// recovery readings via SMS.
class SmsSubscriptionSheet extends ConsumerStatefulWidget {
  const SmsSubscriptionSheet({super.key});

  @override
  ConsumerState<SmsSubscriptionSheet> createState() =>
      _SmsSubscriptionSheetState();
}

class _SmsSubscriptionSheetState extends ConsumerState<SmsSubscriptionSheet> {
  final TextEditingController _phoneController = TextEditingController();
  TimeOfDay _time = const TimeOfDay(hour: 7, minute: 0);
  String _timezone = _detectDefaultTimezone();
  final Set<String> _selectedBooks = {'daily-reflections'};
  bool _sendNow = true;
  bool _consent = false;
  bool _enabled = false;
  bool _busy = false;
  String? _statusMessage;
  bool _isError = false;

  @override
  void initState() {
    super.initState();
    _loadSavedState();
  }

  @override
  void dispose() {
    _phoneController.dispose();
    super.dispose();
  }

  void _loadSavedState() {
    final prefs = ref.read(sharedPreferencesProvider);
    final raw = prefs.getString(_kSmsPrefsKey);
    if (raw != null && raw.isNotEmpty) {
      try {
        final map = jsonDecode(raw) as Map<String, dynamic>;
        final phone = (map['phone'] as String?) ?? '';
        if (phone.isNotEmpty) {
          _phoneController.text = phone;
        }
        final dt = (map['delivery_time'] as String?) ?? '07:00';
        final parts = dt.split(':');
        if (parts.length == 2) {
          _time = TimeOfDay(
            hour: int.tryParse(parts[0]) ?? 7,
            minute: int.tryParse(parts[1]) ?? 0,
          );
        }
        final tz = map['timezone'] as String?;
        if (tz != null && kTimezoneOptions.any((o) => o.iana == tz)) {
          _timezone = tz;
        }
        final b = map['books'];
        if (b is List && b.isNotEmpty) {
          _selectedBooks
            ..clear()
            ..addAll(b.map((e) => e.toString()));
        }
        _enabled = map['enabled'] == true;
        _consent = _enabled;
      } catch (_) {}
    }
  }

  Future<void> _saveLocal(Map<String, dynamic> sub) async {
    final prefs = ref.read(sharedPreferencesProvider);
    await prefs.setString(_kSmsPrefsKey, jsonEncode(sub));
  }

  String _timeToHhMm(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  void _applyServerSubscription(Map<String, dynamic> sub) {
    final dt = (sub['delivery_time'] as String?) ?? '07:00';
    final parts = dt.split(':');
    final tz = (sub['timezone'] as String?) ?? _timezone;
    final books = sub['books'];
    final enabled = sub['enabled'] == true;
    final phone = (sub['phone'] as String?) ?? _phoneController.text.trim();

    setState(() {
      _phoneController.text = phone;
      if (parts.length == 2) {
        _time = TimeOfDay(
          hour: int.tryParse(parts[0]) ?? 7,
          minute: int.tryParse(parts[1]) ?? 0,
        );
      }
      if (kTimezoneOptions.any((o) => o.iana == tz)) {
        _timezone = tz;
      }
      if (books is List && books.isNotEmpty) {
        _selectedBooks
          ..clear()
          ..addAll(books.map((e) => e.toString()));
      }
      _enabled = enabled;
      if (enabled) _consent = true;
    });
    _saveLocal({
      'phone': phone,
      'enabled': enabled,
      'delivery_time': dt,
      'timezone': tz,
      'books': _selectedBooks.toList(),
    });
  }

  /// Schedules can't be looked up by phone number: that would tell anyone who
  /// knows a number that its owner is in recovery. Point to SCHEDULE instead.
  void _showScheduleHelp() {
    setState(() {
      _isError = false;
      _statusMessage = "For privacy, schedules can't be looked up by phone "
          'number. Text SCHEDULE to (762) 376-9696 to see yours.';
    });
  }

  Future<void> _submitSchedule() async {
    final phone = _phoneController.text.trim();
    if (phone.isEmpty) {
      setState(() {
        _isError = true;
        _statusMessage = 'Please enter your 10-digit US/Canada phone number.';
      });
      return;
    }
    if (!_consent) {
      setState(() {
        _isError = true;
        _statusMessage =
            'Please check the Optional SMS Consent box to activate daily text delivery.';
      });
      return;
    }
    if (_selectedBooks.isEmpty) {
      _selectedBooks.add('daily-reflections');
    }

    setState(() {
      _busy = true;
      _isError = false;
      _statusMessage = 'Saving your daily SMS schedule…';
    });

    final client = ref.read(httpClientProvider);
    final baseUrl = ref.read(appConfigProvider).baseUrl;
    final uri = Uri.parse('$baseUrl/api/sms/optin');
    try {
      final res = await client
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'phone': phone,
              'consent': true,
              'enabled': true,
              'delivery_time': _timeToHhMm(_time),
              'timezone': _timezone,
              'books': _selectedBooks.toList(),
              'send_now': _sendNow,
            }),
          )
          .timeout(const Duration(seconds: 15));
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      if (res.statusCode >= 200 && res.statusCode < 300) {
        final sub = data['subscription'];
        if (sub is Map<String, dynamic>) {
          _applyServerSubscription(sub);
        }
        setState(() {
          _busy = false;
          _isError = false;
          _statusMessage = (data['message'] as String?) ??
              'Subscribed! Your daily SMS schedule is active.';
        });
      } else {
        setState(() {
          _busy = false;
          _isError = true;
          _statusMessage =
              (data['error'] ?? data['detail'] ?? 'Could not save schedule.')
                  .toString();
        });
      }
    } catch (_) {
      setState(() {
        _busy = false;
        _isError = true;
        _statusMessage = 'Network error saving schedule. Please try again.';
      });
    }
  }

  Future<void> _sendReadingNow() async {
    final phone = _phoneController.text.trim();
    if (phone.isEmpty) {
      setState(() {
        _isError = true;
        _statusMessage = 'Please enter your mobile phone number above first.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _isError = false;
      _statusMessage = "Sending today's reading to your phone…";
    });
    final client = ref.read(httpClientProvider);
    final baseUrl = ref.read(appConfigProvider).baseUrl;
    final uri = Uri.parse('$baseUrl/api/sms/optin');
    try {
      final res = await client
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'phone': phone,
              'action': 'send_now',
              'timezone': _timezone,
              'books': _selectedBooks.isEmpty
                  ? ['daily-reflections']
                  : _selectedBooks.toList(),
            }),
          )
          .timeout(const Duration(seconds: 15));
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      if (res.statusCode >= 200 && res.statusCode < 300) {
        setState(() {
          _busy = false;
          _isError = false;
          _statusMessage = (data['message'] as String?) ??
              "Today's reading has been texted to your phone!";
        });
      } else {
        setState(() {
          _busy = false;
          _isError = true;
          _statusMessage =
              (data['error'] ?? data['detail'] ?? 'Unable to send SMS.')
                  .toString();
        });
      }
    } catch (_) {
      setState(() {
        _busy = false;
        _isError = true;
        _statusMessage = 'Network error sending SMS. Please try again.';
      });
    }
  }

  Future<void> _pauseSubscription() async {
    final phone = _phoneController.text.trim();
    if (phone.isEmpty) {
      setState(() {
        _enabled = false;
        _consent = false;
        _isError = false;
        _statusMessage = 'Daily SMS delivery is paused.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _isError = false;
      _statusMessage = 'Pausing daily SMS delivery…';
    });
    final client = ref.read(httpClientProvider);
    final baseUrl = ref.read(appConfigProvider).baseUrl;
    final uri = Uri.parse('$baseUrl/api/sms/optin');
    try {
      final res = await client
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'phone': phone,
              'action': 'pause',
              'enabled': false,
            }),
          )
          .timeout(const Duration(seconds: 10));
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      final sub = data['subscription'];
      if (sub is Map<String, dynamic>) {
        _applyServerSubscription(sub);
      } else {
        setState(() {
          _enabled = false;
          _consent = false;
        });
      }
      setState(() {
        _busy = false;
        _isError = false;
        _statusMessage = (data['message'] as String?) ??
            'Your daily SMS readings have been paused.';
      });
    } catch (_) {
      setState(() {
        _busy = false;
        _isError = true;
        _statusMessage = 'Could not reach server to pause subscription.';
      });
    }
  }

  Future<void> _pickTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _time,
    );
    if (picked != null && mounted) {
      setState(() => _time = picked);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return SafeArea(
      top: false,
      child: DraggableScrollableSheet(
        initialChildSize: 0.9,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) {
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.sm,
                  AppSpacing.lg,
                  AppSpacing.sm,
                ),
                child: Row(
                  children: [
                    const Icon(Icons.sms_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Daily Reflection SMS',
                            style: theme.textTheme.titleLarge,
                          ),
                          Text(
                            'Scheduled daily readings & 2-way SMS chat',
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.check),
                      tooltip: 'Done',
                      onPressed: () => Navigator.of(context).maybePop(),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView(
                  controller: scrollController,
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    AppSpacing.md,
                    AppSpacing.lg,
                    AppSpacing.xxl,
                  ),
                  children: [
                    Text(
                      'Receive your daily recovery reading via text message at the time of your choice—and reply directly to any reading to talk through how it applies to your day.',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.md),

                    if (_enabled)
                      Container(
                        margin: const EdgeInsets.only(bottom: AppSpacing.md),
                        padding: const EdgeInsets.all(AppSpacing.md),
                        decoration: BoxDecoration(
                          color: AppColors.accentSoft,
                          borderRadius:
                              BorderRadius.circular(AppSpacing.radius),
                          border: Border.all(color: AppColors.accent),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.check_circle,
                                color: AppColors.accent, size: 20),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: Text(
                                'Active schedule: Daily at ${_time.format(context)} (${_shortTz(_timezone)})',
                                style: theme.textTheme.bodyMedium?.copyWith(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),

                    const SectionHeader('Mobile phone number'),
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _phoneController,
                            keyboardType: TextInputType.phone,
                            decoration: const InputDecoration(
                              hintText: '(555) 123-4567',
                              border: OutlineInputBorder(),
                              isDense: true,
                            ),
                          ),
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        OutlinedButton(
                          onPressed: _busy ? null : _showScheduleHelp,
                          child: const Text('Check'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.lg),

                    const SectionHeader('Daily readings to deliver'),
                    const SizedBox(height: AppSpacing.xs),
                    ...kDailyBookOptions.map((book) {
                      final checked = _selectedBooks.contains(book.id);
                      return CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        dense: true,
                        value: checked,
                        title: Row(
                          children: [
                            Expanded(
                              child: Text(
                                book.title,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600),
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: AppColors.accentSoft,
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Text(
                                book.badge,
                                style: theme.textTheme.labelSmall?.copyWith(
                                  color: AppColors.accent,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                        subtitle: Text(book.subtitle),
                        onChanged: (v) {
                          setState(() {
                            if (v == true) {
                              _selectedBooks.add(book.id);
                            } else if (_selectedBooks.length > 1) {
                              _selectedBooks.remove(book.id);
                            }
                          });
                        },
                      );
                    }),
                    const SizedBox(height: AppSpacing.lg),

                    const SectionHeader('Delivery time & timezone'),
                    const SizedBox(height: AppSpacing.xs),
                    Card(
                      margin: EdgeInsets.zero,
                      child: Column(
                        children: [
                          ListTile(
                            leading: const Icon(Icons.schedule),
                            title: const Text('Delivery time'),
                            subtitle: Text(_time.format(context)),
                            trailing:
                                const Text('Change', style: TextStyle(color: AppColors.accent)),
                            onTap: _pickTime,
                          ),
                          const Divider(height: 1),
                          Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: AppSpacing.md,
                              vertical: AppSpacing.xs,
                            ),
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: 'Timezone',
                                border: InputBorder.none,
                              ),
                              child: DropdownButtonHideUnderline(
                                child: DropdownButton<String>(
                                  value: _timezone,
                                  isDense: true,
                                  isExpanded: true,
                                  items: kTimezoneOptions
                                      .map(
                                        (tz) => DropdownMenuItem<String>(
                                          value: tz.iana,
                                          child: Text(tz.label),
                                        ),
                                      )
                                      .toList(),
                                  onChanged: (val) {
                                    if (val != null) {
                                      setState(() => _timezone = val);
                                    }
                                  },
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.md),

                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      controlAffinity: ListTileControlAffinity.leading,
                      dense: true,
                      value: _sendNow,
                      title: const Text(
                        "Also send today's reading right now",
                        style: TextStyle(fontWeight: FontWeight.w600),
                      ),
                      subtitle: const Text(
                        'Get today’s reflection texted immediately when you save',
                      ),
                      onChanged: (v) => setState(() => _sendNow = v ?? false),
                    ),
                    const Divider(),

                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      controlAffinity: ListTileControlAffinity.leading,
                      value: _consent,
                      title: Text(
                        'Optional SMS Consent: I agree to receive recurring automated daily recovery readings and conversational SMS messages from Sobriety Copilot at the phone number above. We will text once to confirm; readings start when you reply YES. Consent is optional. Msg & data rates may apply. Msg frequency varies. Reply STOP to cancel, PAUSE to pause daily readings, or HELP for help.',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                      onChanged: (v) => setState(() => _consent = v ?? false),
                    ),
                    const SizedBox(height: AppSpacing.md),

                    if (_statusMessage != null) ...[
                      Container(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        decoration: BoxDecoration(
                          color: _isError
                              ? AppColors.error.withValues(alpha: 0.12)
                              : AppColors.accentSoft,
                          borderRadius:
                              BorderRadius.circular(AppSpacing.radius),
                          border: Border.all(
                            color:
                                _isError ? AppColors.error : AppColors.accent,
                          ),
                        ),
                        child: Text(
                          _statusMessage!,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: _isError ? AppColors.error : null,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                    ],

                    FilledButton.icon(
                      onPressed: _busy ? null : _submitSchedule,
                      icon: const Icon(Icons.check),
                      label: const Text('Save Daily SMS Schedule'),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _busy ? null : _sendReadingNow,
                            icon: const Icon(Icons.send_outlined, size: 18),
                            label: const Text('Send Today Now'),
                          ),
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _busy ? null : _pauseSubscription,
                            icon: const Icon(Icons.pause_circle_outline,
                                size: 18),
                            label: const Text('Pause Daily SMS'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xl),

                    Card(
                      margin: EdgeInsets.zero,
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Prefer to manage by text message?',
                              style: theme.textTheme.titleSmall?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: AppSpacing.xs),
                            Text(
                              'Text (762) 376-9696 anytime with:\n'
                              '• DAILY 7:00 AM PT — subscribe or change your time\n'
                              '• SEND NOW — get today’s reading immediately\n'
                              '• SCHEDULE — check your active schedule\n'
                              '• PAUSE — pause daily readings\n'
                              '• NEW — start a fresh conversation topic\n'
                              '• STOP — unsubscribe from all SMS',
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: scheme.onSurfaceVariant,
                              ),
                            ),
                            const SizedBox(height: AppSpacing.sm),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: TextButton.icon(
                                icon: const Icon(Icons.sms_outlined, size: 18),
                                label: const Text('Text (762) 376-9696'),
                                onPressed: () => launchUrl(
                                  Uri.parse(
                                      'sms:+17623769696?body=DAILY%207%3A00%20AM%20PT'),
                                  mode: LaunchMode.externalApplication,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
