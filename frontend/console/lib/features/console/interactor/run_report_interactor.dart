import '../model/run_report_model.dart';

/// Presents the language report as recorded; OS material state is a labelled fallback.
class NativeRunReportInteractor {
  bool hasReport(Map result) => result['schema'] == 'lab_report_v1';

  String name(dynamic value, [String fallback = 'Unnamed item']) {
    final text = value?.toString() ?? '';
    return text.isEmpty ||
            text.startsWith('__') ||
            text.startsWith('container/')
        ? fallback
        : text;
  }

  String quantity(Map row, String prefix) {
    for (final unit in const {'uL': 'µL', 'mL': 'mL', 'mg': 'mg'}.entries) {
      final value = row['${prefix}_${unit.key}'];
      if (value is num)
        return '${value == value.roundToDouble() ? value.toInt() : value} ${unit.value}';
    }
    if (prefix == 'volume' && row['mass_mg'] is num)
      return quantity({'amount_mg': row['mass_mg']}, 'amount');
    return 'Not reported';
  }

  List<NativeReportSection> describe(Map result) {
    if (!hasReport(result)) return legacyAmounts(result);
    final materials = result['materials'] as Map? ?? {};
    final sections = <NativeReportSection>[];
    for (final definition in const [
      ['final_products', 'Final products', 'Amount', 'volume'],
      ['input_inventory', 'Starting materials', 'Initial amount', 'initial'],
      ['reagent_consumption', 'Reagents used', 'Consumed', 'consumed'],
      ['intermediate_materials', 'Intermediate materials', 'Amount', 'volume'],
    ]) {
      final values = materials[definition[0]] as List? ?? [];
      if (values.isNotEmpty)
        sections.add(
          NativeReportSection(
            definition[1],
            ['Material', definition[2]],
            [
              for (final row in values)
                [name(row['name']), quantity(row, definition[3])],
            ],
          ),
        );
    }
    final containers = result['resource_summary']?['containers'] as Map? ?? {};
    final counts = containers['container_kinds'] as List? ?? [];
    if (counts.isNotEmpty)
      sections.add(
        NativeReportSection(
          'Container usage',
          ['Kind', 'Count'],
          [
            for (final row in counts)
              [name(row['kind']), row['count']?.toString() ?? 'Not reported'],
          ],
        ),
      );
    final instruments =
        result['resource_summary']?['instruments'] as Map? ?? {};
    final devices = <List<String>>[];
    for (final category in const ['tools', 'devices']) {
      for (final row in instruments[category] as List? ?? []) {
        devices.add([
          name(row['name']),
          row['count']?.toString() ?? 'Not reported',
        ]);
      }
    }
    if (devices.isNotEmpty)
      sections.add(
        NativeReportSection('Declared instruments', [
          'Instrument',
          'References in program',
        ], devices),
      );
    final process = result['process_summary'] as Map? ?? {};
    final operations = <List<String>>[];
    for (final field in const {
      'mutation_steps': 'Liquid operations',
      'environment_steps': 'Environment operations',
      'separation_steps': 'Separation operations',
      'readout_steps': 'Readout operations',
    }.entries) {
      if (process[field.key] is num && process[field.key] > 0)
        operations.add([field.value, '${process[field.key]}']);
    }
    if (operations.isNotEmpty)
      sections.add(
        NativeReportSection('Program summary', [
          'Operation',
          'Language steps',
        ], operations),
      );
    return sections;
  }

  List<NativeReportSection> legacyAmounts(Map result) {
    final containers =
        result['os']?['registered_material']?['state']?['containers'] as Map? ??
        {};
    if (containers.isEmpty) return [];
    var index = 0;
    return [
      NativeReportSection(
        'Recorded material amounts',
        ['Container', 'Amount'],
        [
          for (final value in containers.values)
            [
              name(
                value['metadata']?['label'],
                name(
                  value['metadata']?['allocation_name'],
                  'Container ${++index}',
                ),
              ),
              quantity(value, 'volume'),
            ],
        ],
      ),
    ];
  }
}
