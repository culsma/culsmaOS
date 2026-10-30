import 'dart:convert';
import 'package:flutter/material.dart';
import '../../layout/model/layout_model.dart';
import '../interactor/console_interactor.dart';

class NativeInfoTable extends StatefulWidget {
  final List<String> columns;
  final List<List<dynamic>> rows;
  final String empty;
  const NativeInfoTable({
    super.key,
    required this.columns,
    required this.rows,
    this.empty = 'No records in this snapshot.',
  });
  static String display(dynamic value) {
    if (value == null) return 'Not recorded';
    final text = value is Map || value is List
        ? jsonEncode(value)
        : value.toString();
    return text.length > 500 ? '${text.substring(0, 500)}… (preview)' : text;
  }

  @override
  State<NativeInfoTable> createState() => NativeInfoTableState();
}

class NativeInfoTableState extends State<NativeInfoTable> {
  // ExpansionTile stores a bool in PageStorage. Own the table's scroll state so
  // horizontal positions never share that key or reset during snapshot polling.
  final scroll = ScrollController(keepScrollOffset: false);
  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final rows = widget.rows, columns = widget.columns, empty = widget.empty;
    if (rows.isEmpty)
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Text(empty),
      );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SingleChildScrollView(
          controller: scroll,
          scrollDirection: Axis.horizontal,
          child: DataTable(
            dataRowMinHeight: 40,
            dataRowMaxHeight: 56,
            columns: [
              for (final label in columns) DataColumn(label: Text(label)),
            ],
            rows: [
              for (final row in rows.take(200))
                DataRow(
                  cells: [
                    for (final value in row)
                      DataCell(
                        SizedBox(
                          width: 220,
                          child: Text(
                            NativeInfoTable.display(value),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ),
                  ],
                ),
            ],
          ),
        ),
        if (rows.length > 200)
          const Text(
            'Showing 200 records. The complete snapshot is available through the OS API.',
          ),
      ],
    );
  }
}

class NativeSystemInformationView extends StatelessWidget {
  final NativeConsoleInteractor console;
  const NativeSystemInformationView({super.key, required this.console});
  Widget section(
    String id,
    String title,
    List<Widget> children, {
    bool expanded = false,
  }) => Card(
    child: ExpansionTile(
      key: PageStorageKey('system-info:$id'),
      initiallyExpanded: expanded,
      title: Text(title),
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      children: [
        for (final child in children)
          Align(alignment: Alignment.centerLeft, child: child),
      ],
    ),
  );
  Widget facts(Map<String, dynamic> values) => NativeInfoTable(
    columns: const ['Item', 'Recorded value'],
    rows: [
      for (final row in values.entries) [row.key, row.value],
    ],
  );
  Widget records(
    String title,
    List<dynamic>? rows,
    List<String> labels,
    List<String> fields,
  ) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
      NativeInfoTable(
        columns: labels,
        rows: [
          for (final row in rows ?? [])
            [for (final field in fields) row[field]],
        ],
      ),
      const SizedBox(height: 16),
    ],
  );
  @override
  Widget build(BuildContext context) {
    final c = console,
        info = c.information,
        station = c.station,
        inspection = station?['devices'] as Map? ?? {},
        resources = inspection['resources'] as Map? ?? {},
        host = station?['host'] as Map? ?? {},
        configuration = info.record?['configuration'] as Map? ?? {},
        profile = info.profile(c.layout.profiles);
    return ListView(
      key: const PageStorageKey('system-info-scroll'),
      padding: const EdgeInsets.all(24),
      children: [
        const Text(
          'System Info',
          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        const Text(
          'Read-only OS records and declared configuration. Hardware presence and physical contents are not detected.',
        ),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: c.busy ? null : c.refresh,
            icon: const Icon(Icons.refresh),
            label: const Text('Refresh system information'),
          ),
        ),
        if (info.error != null)
          Text(info.error!, style: const TextStyle(color: Color(0xff924e25))),
        section('equipment', 'Platform and equipment', [
          facts({
            'Active configuration':
                station?['layout']?['configuration_fingerprint'],
            'Active driver': station?['layout']?['driver'],
            'Saved setup': info.active?['active']?['origin']?['title'],
            'Saved revision': info.active?['active']?['origin']?['revision'],
          }),
          NativeInfoTable(
            columns: const ['Parameter', 'Configured value'],
            rows: info.equipment(c.layout.profiles),
            empty: info.record == null
                ? 'No matching saved active configuration is available. Editable proposals are not used as system facts.'
                : 'The installed driver does not expose structured equipment fields.',
          ),
          for (final summary in profile?['summaries'] as List? ?? [])
            if (info.record != null)
              records(
                summary['label'],
                [
                  for (final row
                      in (LayoutData.at(
                                    Map<String, dynamic>.from(configuration),
                                    summary['path'],
                                  )
                                  as Map? ??
                              {})
                          .entries)
                    {'name': row.key, ...Map<String, dynamic>.from(row.value)},
                ],
                ['Name', ...List<String>.from(summary['columns'])],
                ['name', ...List<String>.from(summary['columns'])],
              ),
        ], expanded: true),
        section('devices', 'Device state and consumables', [
          facts({
            'Device records': inspection['registration'],
            'Snapshot consistency': inspection['consistency'],
            'Observed at': inspection['observed_at'],
          }),
          if ((inspection['devices'] as List? ?? []).isEmpty)
            const Text('No device records are available yet.'),
          for (final device in inspection['devices'] as List? ?? []) ...[
            Text(
              device['device_id'],
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
            ),
            facts({
              'Mode': device['mode'],
              'Configuration revision': device['configuration_revision'],
              'Calibration revision': device['calibration_revision'],
              'Evidence accounting': device['evidence_accounting'],
              'Position basis': device['positions']?['status'],
            }),
            NativeInfoTable(
              columns: const [
                'Resource',
                'Lifetime used',
                'Current box used',
                'Loaded capacity',
                'Available from records',
              ],
              rows: [
                for (final row in (device['consumables'] as Map? ?? {}).entries)
                  [
                    row.key,
                    row.value['known_consumed'],
                    row.value['current_load_consumed'],
                    row.value['loaded_capacity'] ??
                        row.value['configured_capacity'],
                    row.value['available_from_records'] ?? 'Unknown',
                  ],
              ],
            ),
            const Text('Recorded plate locations'),
            NativeInfoTable(
              columns: const ['Labware', 'Recorded position'],
              rows: [
                for (final row
                    in (device['positions']?['current'] as Map? ?? {}).entries)
                  [row.key, row.value],
              ],
              empty: device['positions']?['status'] == 'unknown'
                  ? 'Positions are unknown. Isolation is retained.'
                  : 'No positions declared.',
            ),
            if ((device['positions']?['unresolved_motion'] as List? ?? [])
                .isNotEmpty)
              Text(
                'Position uncertainty: ${(device['positions']['unresolved_motion'] as List).join(', ')}',
              ),
            records(
              'Unresolved operations',
              device['unresolved_operations'],
              ['Run', 'Step', 'Operation', 'Status'],
              ['run_id', 'step_id', 'operation_kind', 'status'],
            ),
          ],
        ]),
        section('resources', 'Resource accounting and ownership', [
          facts({
            'Local accounting': resources['local_accounting'],
            'Station accounting': resources['station_accounting'],
          }),
          records(
            'Station reservations',
            resources['station_reservations'],
            ['Run', 'Owner', 'State'],
            ['run_id', 'owner_id', 'status'],
          ),
          records(
            'Station locks',
            resources['station_locks'],
            ['Resource', 'Run'],
            ['resource_id', 'run_id'],
          ),
          records(
            'Local locks',
            resources['locks'],
            ['Resource', 'Attempt'],
            ['resource_id', 'attempt_id'],
          ),
          records(
            'Active permits',
            resources['permits'],
            ['Attempt', 'Effect', 'State'],
            ['attempt_id', 'effect_id', 'status'],
          ),
          records(
            'Tip-box loading records',
            resources['supply_loads'],
            ['Request', 'Resource', 'State', 'Lifetime baseline'],
            ['request_id', 'resource_id', 'status', 'baseline'],
          ),
        ]),
        section('drivers', 'Drivers and capabilities', [
          const Text('Current workstation capabilities'),
          NativeInfoTable(
            columns: const ['Operation', 'Availability', 'Details'],
            rows: [
              for (final entry
                  in (host['capabilities']?['features'] as Map? ?? {}).entries)
                [
                  entry.key.toString().replaceAll('_', ' '),
                  entry.value['supported'] == true
                      ? 'Supported'
                      : 'Not applicable / unavailable',
                  entry.value['reason'] ?? 'Provided by the configured driver',
                ],
            ],
          ),
          const Text(
            'Installed plugin metadata describes supported choices; it does not establish which hardware is connected.',
          ),
          for (final p in c.layout.profiles) ...[
            Text(
              p['label'] ?? p['driver'],
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
            ),
            facts({
              'Installed driver': p['driver'],
              'Configuration schema': p['schema'],
              'Activation supported': p['activation_supported'],
              'Layout export supported': p['layout_export_supported'],
            }),
            NativeInfoTable(
              columns: const ['Parameter', 'Supported choices'],
              rows: [
                for (final field in p['fields'] as List? ?? [])
                  if (field['options'] != null &&
                      {'platform', 'instruments'}.contains(field['section']))
                    [field['label'], field['options']],
              ],
            ),
            NativeInfoTable(
              columns: const ['Layout model', 'Category'],
              rows: [
                for (final model in p['layout']?['catalogue'] as List? ?? [])
                  [model['label'] ?? model['id'], model['category']],
              ],
            ),
          ],
        ]),
        section('runtime', 'Runtime environment', [
          facts({
            'Execution mode': configuration['mode'],
            'Execution strategy': configuration['execution_strategy'],
            'Simulation backend': configuration['agent']?['simulation_backend'],
          }),
          const Text(
            'These declarations require a matching saved active configuration. Run evidence identifies the backend actually used. Intermediate hardware progress is not inferred from a batch receipt.',
          ),
          const Text(
            'A unified OS and driver version report and shared live module observations are not exposed by the current API.',
          ),
        ]),
        section('service', 'Resident service and connection', [
          facts({
            'Status': host['status'],
            'Blocked run': host['blocked_run'],
            'Blocking reason': host['blocked_reason'],
            'Worker error': host['worker_error'],
          }),
          const Text(
            'Agent connection diagnostics, serial ports, USB identifiers, firmware and detected physical contents are not reported by the current console API.',
          ),
        ]),
      ],
    );
  }
}
