import 'package:flutter/material.dart';
import '../interactor/run_report_interactor.dart';

/// User-facing report, separate from device evidence and physical measurements.
class NativeRunReportPanel extends StatelessWidget {
  final Map run;
  const NativeRunReportPanel({super.key, required this.run});
  @override
  Widget build(BuildContext context) {
    final result = run['result'] as Map? ?? {};
    final presenter = NativeRunReportInteractor();
    final sections = presenter.describe(result);
    final complete = run['status'] == 'completed';
    if (!complete && sections.isEmpty && !presenter.hasReport(result))
      return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 24),
        if (!complete && sections.isNotEmpty)
          const Text('Partial run report · the experiment did not complete.'),
        if (presenter.hasReport(result))
          const Text(
            'Experiment report',
            style: TextStyle(fontSize: 21, fontWeight: FontWeight.w600),
          ),
        if (presenter.hasReport(result))
          const Text(
            'From the Culsma language result. Quantities are calculated, not physical measurements.',
          ),
        if (sections.isEmpty && complete)
          const Text('No material report was recorded for this run.'),
        for (final section in sections)
          Padding(
            padding: const EdgeInsets.only(top: 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  section.title,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columns: [
                      for (final title in section.columns)
                        DataColumn(label: Text(title)),
                    ],
                    rows: [
                      for (final row in section.rows)
                        DataRow(
                          cells: [for (final cell in row) DataCell(Text(cell))],
                        ),
                    ],
                  ),
                ),
                if (section.title == 'Container usage')
                  const Text(
                    'Wells are counted individually; this is not a count of physical plates.',
                  ),
                if (section.title == 'Program summary')
                  const Text(
                    'Language operations can include multiple device actions.',
                  ),
              ],
            ),
          ),
        if (presenter.hasReport(result)) ...[
          const SizedBox(height: 20),
          if ((result['resource_summary']?['instruments']?['devices']
                          as List? ??
                      [])
                  .isEmpty &&
              (result['resource_summary']?['instruments']?['tools'] as List? ??
                      [])
                  .isEmpty)
            const Text(
              'No explicit instrument requirements were recorded in the language report. Device execution evidence is available in Technical details.',
            ),
          const Text('No duration estimate is supplied by this report.'),
          if (result['external_inventory']?['checked'] == false)
            const Text('External stock availability was not checked.'),
          for (final alert in result['alerts'] as List? ?? [])
            Text('Report alert: $alert'),
          if ((result['qc_results'] as List? ?? []).isNotEmpty)
            ExpansionTile(
              title: const Text('Recorded QC results'),
              children: [
                for (final qc in result['qc_results'])
                  ListTile(
                    title: Text(qc['item']?.toString() ?? 'QC result'),
                    subtitle: Text(qc.toString()),
                  ),
              ],
            ),
        ],
      ],
    );
  }
}
