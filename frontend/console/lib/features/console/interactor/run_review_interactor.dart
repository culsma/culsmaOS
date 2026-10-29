/// Presents the existing loading plan without inventing inventory or hardware facts.
class NativeRunReviewInteractor {
  bool simulationAvailable(Map? station, [Map? inspection]) {
    final options = inspection?['preparation']?['execution_options'];
    if (options is Map) return options['simulation'] == true;
    final devices = station?['devices']?['devices'] as List? ?? [];
    return devices.isNotEmpty &&
        devices.every((d) => d['mode'] == 'simulation');
  }

  String location(Map? placement) {
    final parts = <String>[];
    for (final field in const {
      'track': 'Track',
      'slot': 'Slot',
      'site': 'Position',
    }.entries) {
      final value = placement?[field.key];
      if (value != null && value.toString().isNotEmpty)
        parts.add('${field.value} $value');
    }
    if (parts.isEmpty && placement?['carrier'] != null)
      parts.add('Carrier ${placement!['carrier']}');
    return parts.isEmpty
        ? 'Location not supplied by the driver'
        : parts.join(' · ');
  }

  String volume(dynamic value) {
    if (value is! num) return 'Amount not specified';
    return '${value == value.roundToDouble() ? value.toInt() : value} µL';
  }

  String containerInstruction(Map vessel) {
    final name = vessel['name']?.toString() ?? '';
    final well = vessel['well']?.toString() ?? '?';
    final label = name.isEmpty || name.startsWith('__lw_')
        ? 'Well $well'
        : '$name · position $well';
    return vessel['volume_uL'] == 0
        ? '$label — leave empty'
        : '$label — load ${volume(vessel['volume_uL'])}';
  }

  String tipInstruction(Map supply) {
    final required = supply['required'];
    final count = supply['positions'] is List
        ? (supply['positions'] as List).length
        : null;
    return '${supply['model'] ?? 'Tip rack'} · ${location(supply)}\n'
        '${count == null ? 'Tip positions not specified' : '$count configured tip positions'}. '
        '${required == null ? 'Required quantity and remaining stock are checked before execution.' : '$required tips required; remaining stock is checked before execution.'}';
  }
}
