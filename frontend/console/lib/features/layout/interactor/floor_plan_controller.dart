import 'package:flutter/foundation.dart';
import '../../../api/console_api.dart';
import '../model/layout_model.dart';

class FloorPlanController extends ChangeNotifier {
  FloorPlanController(this.api);
  final ConsoleApi api;
  static const endpoint = '/api/v1/configuration/floor-plan';
  Map<String, dynamic>? state;
  Map<String, dynamic>? plan;
  String? message;
  bool busy = false, uncertain = false, _disposed = false;

  bool get dirty =>
      plan != null &&
      LayoutData.canonical(plan) != LayoutData.canonical(state?['draft']);
  bool get checked =>
      state?['checked_fingerprint'] != null &&
      state?['checked_fingerprint'] == state?['configuration_fingerprint'];
  bool get editable => plan != null && !busy && !uncertain;
  List<Map<String, dynamic>> rows(String key) =>
      List<Map<String, dynamic>>.from(plan?[key] ?? const []);

  void update(String key, List<Map<String, dynamic>> value) {
    if (!editable) return;
    plan = {...plan!, key: value};
    message = null;
    notifyListeners();
  }

  void setDeck(int width, int height) {
    if (!editable) return;
    final deck = {'width': width, 'height': height};
    if (plan!['deck'] != null) {
      plan = {...plan!, 'deck': deck};
    } else {
      int scale(num value, int extent) => (value * extent / 100).round();
      final areas = [
        for (final row in rows('areas'))
          {
            ...row,
            'x': scale(row['x'], width),
            'y': scale(row['y'], height),
            'width':
                scale(row['x'] + row['width'], width) - scale(row['x'], width),
            'height':
                scale(row['y'] + row['height'], height) -
                scale(row['y'], height),
            'level': 'deck',
          },
      ];
      final areasById = {for (final area in areas) area['id']: area};
      plan = {
        'deck': deck,
        'areas': areas,
        'equipment': [
          for (final item in rows('equipment'))
            {
              ...item,
              'x': scale(item['x'], areasById[item['area_id']]!['width']),
              'y': scale(item['y'], areasById[item['area_id']]!['height']),
            },
        ],
      };
    }
    message = null;
    notifyListeners();
  }

  void discard() {
    if (!editable) return;
    plan = LayoutData.copy(state!['draft']);
    message = null;
    notifyListeners();
  }

  Future<bool> submit(String action) async {
    if (busy ||
        (action != 'read' &&
            (!editable ||
                (action != 'save' && dirty) ||
                (action == 'apply' && !checked))))
      return false;
    busy = true;
    message = null;
    notifyListeners();
    try {
      final result = await api.command(endpoint, {
        'action': action,
        if (action != 'read') ...{
          'revision': state!['revision'],
          'configuration_fingerprint': state!['configuration_fingerprint'],
        },
        if (action == 'save') 'plan': plan,
      });
      if (_disposed) return false;
      state = result;
      plan = LayoutData.copy(result['draft']);
      uncertain = false;
      message = switch (action) {
        'save' => 'Draft saved.',
        'check' => 'Layout checked. Apply it to show it in Workstation.',
        'apply' => 'Layout applied.',
        _ => null,
      };
      return true;
    } on ConsoleApiError catch (error) {
      uncertain =
          error.responseUnknown ||
          error.code == 'FLOOR_PLAN_REVISION_CONFLICT' ||
          error.code == 'HOST_CONFIGURATION_STALE';
      message = uncertain
          ? 'Reload the saved layout before making another change.'
          : switch (error.code) {
              'FLOOR_PLAN_AREA_OVERLAP' =>
                'An expansion area overlaps another area or the deck on the same level.',
              'FLOOR_PLAN_AREA_INVALID' =>
                'Check the expansion area name and dimensions.',
              'FLOOR_PLAN_EQUIPMENT_OVERLAP' => 'Two instruments overlap.',
              'FLOOR_PLAN_EQUIPMENT_OUTSIDE' =>
                'An instrument does not fit inside its area.',
              'FLOOR_PLAN_DECK_INVALID' =>
                'Enter a positive deck width and depth in millimetres.',
              'FLOOR_PLAN_INSTRUMENT_UNAVAILABLE' =>
                'An instrument is missing from the current station.',
              'FLOOR_PLAN_INSTRUMENT_INVALID' =>
                'An instrument is assigned more than once or has a different type.',
              'HOST_CONFIGURATION_BUSY' =>
                'Wait for the workstation to become idle before applying.',
              _ => error.code,
            };
      return false;
    } finally {
      busy = false;
      if (!_disposed) notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
