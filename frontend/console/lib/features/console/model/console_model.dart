import 'dart:ui';

class ConsoleWindowModel {
  final String id, view, title;
  final String? entityId;
  Rect bounds;
  bool minimized = false, maximized = false;
  ConsoleWindowModel(
    this.id,
    this.view,
    this.title,
    this.entityId,
    this.bounds,
  );
}

class ConsoleWindowDescriptor {
  final String view, label;
  const ConsoleWindowDescriptor(this.view, this.label);
  static const applications = [
    ConsoleWindowDescriptor('files', 'Files'),
    ConsoleWindowDescriptor('workstation', 'Workstation'),
    ConsoleWindowDescriptor('settings', 'System Settings'),
    ConsoleWindowDescriptor('system_info', 'System Info'),
  ];
}

/// Validated presentation geometry supplied by the owning driver through the OS.
class RecordedDeck {
  final String label;
  final List<Map<String, dynamic>> positions, carriers;
  RecordedDeck(this.label, this.positions, this.carriers);

  /// Presentation labels follow carrier order, independently of physical rails.
  static String carrierLabel(int index) {
    if (index < 0) throw RangeError.value(index, 'index');
    var value = index + 1, label = '';
    while (value > 0) {
      value--;
      label = String.fromCharCode(65 + value % 26) + label;
      value ~/= 26;
    }
    return label;
  }

  static RecordedDeck? fromLayout(Map<String, dynamic>? envelope) {
    if (envelope?['status'] != 'available') return null;
    final definition = envelope?['layout']?['definition'];
    final scene = definition?['diagram']?['scene'];
    if (scene is! Map ||
        scene['positions'] is! List ||
        scene['carriers'] is! List)
      return null;
    final positions = List<Map<String, dynamic>>.from(scene['positions']);
    final carriers = List<Map<String, dynamic>>.from(scene['carriers']);
    if (positions.isEmpty || positions.length > 128 || carriers.length > 128)
      return null;
    for (final c in carriers) {
      if (c['start'] is! int ||
          c['span'] is! int ||
          c['start'] < 0 ||
          c['span'] < 1 ||
          c['start'] + c['span'] > positions.length ||
          c['sites'] is! List ||
          c['sites'].isEmpty ||
          c['sites'].length > 16 ||
          c['placements'] is! List)
        return null;
    }
    return RecordedDeck(
      scene['label']?.toString() ?? 'Configured deck',
      positions,
      carriers,
    );
  }
}
