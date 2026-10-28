import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../../layout/model/layout_model.dart';

/// Reads saved active facts separately from editable layout proposals.
class NativeSystemInformationInteractor extends ChangeNotifier {
  final ConsoleApi api;
  Map<String, dynamic>? active, record;
  String? error;
  bool busy = false, disposed = false;
  NativeSystemInformationInteractor(this.api);
  Future<void> observe(Map<String, dynamic>? station) async {
    if (busy || disposed) return;
    busy = true;
    try {
      final view = await api.read('/api/v1/configuration/active');
      final origin = view['active']?['origin'];
      final fingerprint = view['active']?['fingerprint'];
      final layoutFingerprint =
          station?['layout']?['configuration_fingerprint'];
      if (layoutFingerprint != null && fingerprint != layoutFingerprint)
        throw const FormatException(
          'Active configuration changed; refreshing its facts.',
        );
      Map<String, dynamic>? current;
      if (origin is Map) {
        if (record != null &&
            matches(record!, origin) &&
            active?['active']?['fingerprint'] == fingerprint)
          current = record;
        else {
          final reply = await api.command('/api/v1/configuration/drafts', {
            'action': 'get',
            'draft_id': origin['draft_id'],
            'revision': origin['revision'],
          });
          current = Map<String, dynamic>.from(reply['draft']);
          if (!matches(current, origin))
            throw const FormatException(
              'Saved active configuration identity does not match.',
            );
          final verified = await api.read('/api/v1/configuration/active');
          if (verified['active']?['fingerprint'] != fingerprint)
            throw const FormatException(
              'Active configuration changed while reading its facts.',
            );
        }
      }
      active = view;
      record = current;
      error = null;
    } catch (e) {
      active = null;
      record = null;
      error = e.toString();
    } finally {
      busy = false;
      if (!disposed) notifyListeners();
    }
  }

  bool matches(Map<String, dynamic> value, Map origin) =>
      value['draft_id'] == origin['draft_id'] &&
      value['revision'] == origin['revision'] &&
      value['fingerprint'] == origin['configuration_fingerprint'];
  Map<String, dynamic>? profile(List<Map<String, dynamic>> installed) =>
      installed.where((p) => p['driver'] == record?['driver']).firstOrNull;
  List<List<dynamic>> equipment(List<Map<String, dynamic>> installed) {
    final p = profile(installed), configuration = record?['configuration'];
    if (p == null || configuration is! Map<String, dynamic>) return [];
    return [
      for (final field in p['fields'] as List? ?? [])
        if ({'platform', 'instruments'}.contains(field['section']))
          [field['label'], LayoutData.at(configuration, field['path'])],
    ];
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}
