import 'package:flutter/material.dart';
import '../interactor/console_interactor.dart';
import 'supply_panel.dart';
import 'setup_panel.dart';
import 'run_control_panel.dart';
import 'evidence_panel.dart';
import 'run_report_panel.dart';
import 'fault_context.dart';
import 'run_progress_panel.dart';

/// Renders backend guidance. Recovery eligibility is never inferred from raw errors.
class NativeRunOutcomeView extends StatelessWidget {
  final NativeConsoleInteractor console;
  final Map<String, dynamic> run;
  const NativeRunOutcomeView({
    super.key,
    required this.console,
    required this.run,
  });
  String fallbackTitle() => switch (run['status']) {
    'completed' => 'Experiment complete',
    'failed' || 'rejected' => 'The experiment stopped',
    'paused' => 'Experiment paused',
    'cancelled' => 'Experiment cancelled',
    'awaiting_setup' => 'Prepare the experiment',
    'ready' || 'queued' => 'Preparing the experiment',
    _ => 'Experiment in progress',
  };
  Widget details(Map result, String id) => ExpansionTile(
    key: ValueKey('run-technical-$id'),
    title: const Text('Technical details'),
    subtitle: const Text('Run identifier, diagnostics and execution records'),
    children: [
      ListTile(
        title: const Text('Run identifier'),
        subtitle: SelectableText(id),
      ),
      ListTile(
        title: const Text('Recorded status'),
        subtitle: Text(run['status'] ?? 'unavailable'),
      ),
      if (run['error'] != null)
        ListTile(
          title: const Text('Diagnostic'),
          subtitle: SelectableText(run['error']),
        ),
      if (result['execution'] != null)
        ListTile(
          title: const Text('Language execution'),
          subtitle: Text(
            '${result['execution']['completed_steps']} / ${result['execution']['total_steps']} semantic steps. These are not device actions.',
          ),
        ),
      NativeEvidencePanel(run: run),
      NativeEvidencePanel(run: run).details('Complete language report', {
        for (final entry in result.entries)
          if (entry.key != 'os') entry.key: entry.value,
      }),
      if (run['status'] != 'awaiting_setup' && console.setup.plans[id] != null)
        ExpansionTile(
          title: const Text('Recorded loading plan'),
          children: [NativeSetupPanel(controller: console.setup, run: run)],
        ),
    ],
  );
  @override
  Widget build(BuildContext context) {
    final id = run['run_id'] as String;
    final guidance = run['user_guidance'] as Map? ?? {};
    final actions = guidance['actions'] as List? ?? [];
    final result = run['result'] as Map? ?? {};
    final workflow = result['os']?['workflow_simulation'] as Map?;
    final internal = workflow?['steps'] as List? ?? [];
    final preparation = guidance['kind'] == 'preparation';
    final currentSupply = console.supplies.data;
    final available = currentSupply?['stock']?['available'] as List?;
    final replace = actions.contains('replace_tips');
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              run['status'] == 'completed'
                  ? Icons.check_circle_outline
                  : preparation
                  ? Icons.inventory_2_outlined
                  : Icons.info_outline,
              color: run['status'] == 'completed'
                  ? const Color(0xff26734d)
                  : const Color(0xff72521e),
              size: 30,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                run['status'] == 'completed' &&
                        result['os']?['mode'] == 'simulation'
                    ? 'Simulation completed'
                    : guidance['title'] ?? fallbackTitle(),
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
          ],
        ),
        if (result['os']?['mode'] == 'simulation')
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: Text(
              'Execution mode: simulation · physical instruments were not used',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        const SizedBox(height: 12),
        Text(
          guidance['message'] ??
              (run['status'] == 'completed'
                  ? 'Review the recorded results below.'
                  : 'Review the workstation and run controls below.'),
        ),
        if (workflow != null)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Workflow simulation'),
            subtitle: Text(
              internal.isEmpty
                  ? 'All device actions used the workstation simulation.'
                  : 'Device actions use the workstation simulation. Readouts listed below are synthetic.',
            ),
          ),
        for (final row in internal)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Fluorescence · internal simulation'),
            subtitle: Text(
              row['status'] == 'completed'
                  ? 'Synthetic signal: ${row['result']['signal']}'
                  : 'Planned · no result recorded',
            ),
          ),
        NativeRunProgressPanel(run: run),
        NativeFaultContext(guidance: guidance),
        if (guidance['device_activity'] == 'none_recorded')
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('No device execution was recorded for this attempt.'),
          ),
        if ((guidance['next_steps'] as List? ?? []).isNotEmpty ||
            actions.isNotEmpty)
          Card(
            margin: const EdgeInsets.symmetric(vertical: 20),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'What to do next',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                  ),
                  if (replace && available != null)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      child: Text(
                        'Current tip supply: ${available.length} available',
                        key: const Key('run-tip-availability'),
                      ),
                    ),
                  if (replace && available == null)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 10),
                      child: Text(
                        'Current tip quantity is not available. Review the workstation loading.',
                      ),
                    ),
                  for (final entry
                      in (guidance['next_steps'] as List? ?? [])
                          .asMap()
                          .entries)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Text(
                        guidance['context'] == null
                            ? entry.value
                            : '${entry.key + 1}. ${entry.value}',
                      ),
                    ),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      if (replace &&
                          console.supplies.supported &&
                          currentSupply?['mode'] == 'simulation')
                        FilledButton.icon(
                          key: const Key('run-replace-tips'),
                          onPressed: console.working
                              ? null
                              : () => showTipReplacement(context, console),
                          icon: const Icon(Icons.inventory_2_outlined),
                          label: const Text('Replace tip box…'),
                        ),
                      if (actions.contains('open_workstation') ||
                          replace &&
                              (!console.supplies.supported ||
                                  currentSupply?['mode'] != 'simulation'))
                        OutlinedButton(
                          onPressed: () {
                            console.open('workstation');
                            console.refresh();
                          },
                          child: const Text('Review workstation'),
                        ),
                      if (actions.contains('refresh'))
                        OutlinedButton.icon(
                          key: const Key('run-refresh-preparation'),
                          onPressed: console.working ? null : console.refresh,
                          icon: const Icon(Icons.refresh),
                          label: Text(
                            replace ? 'Check supplies again' : 'Refresh status',
                          ),
                        ),
                      if (actions.contains('open_files'))
                        TextButton(
                          key: const Key('run-open-files'),
                          onPressed: () => console.open('files'),
                          child: const Text('Open experiment files'),
                        ),
                    ],
                  ),
                  if (replace && console.supplies.message != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(console.supplies.message!),
                    ),
                  if (replace && console.supplies.error != null)
                    const Padding(
                      padding: EdgeInsets.only(top: 12),
                      child: Text(
                        'Tip supply information could not be updated. Review the workstation before starting a new run.',
                      ),
                    ),
                ],
              ),
            ),
          ),
        NativeRunControlPanel(controller: console.controls, run: run),
        if (run['status'] == 'awaiting_setup')
          NativeSetupPanel(controller: console.setup, run: run),
        NativeRunReportPanel(run: run),
        const SizedBox(height: 24),
        details(result, id),
      ],
    );
  }
}
