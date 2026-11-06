import 'package:flutter/material.dart';
import '../interactor/console_interactor.dart';
import 'preparation_layout.dart';

/// A loading review and an explicit simulation action, never a hardware claim.
class NativeRunReviewView extends StatelessWidget {
  final NativeConsoleInteractor console;
  const NativeRunReviewView({super.key, required this.console});

  @override
  Widget build(BuildContext context) {
    final c = console;
    final preparation = c.inspection?['preparation'];
    final plan = preparation?['plan'] as Map? ?? {};
    final workflow = preparation?['workflow_simulation'] as Map?;
    final internal = workflow?['routes'] as Map? ?? {};
    final checked = c.launchReview != null;
    final simulation = c.review.simulationAvailable(c.station, c.inspection);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 20, 24, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                c.startingSimulation
                    ? 'Starting the simulation…'
                    : c.checkingRun
                    ? 'Checking the experiment…'
                    : checked
                    ? 'Ready to confirm'
                    : 'Check needs attention',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 8),
              Text(c.selectedFile ?? ''),
              const SizedBox(height: 8),
              Text(
                c.startingSimulation
                    ? 'Submitting the run. Its progress and result will open automatically. Please do not start it again.'
                    : 'Review the loading plan below. No experiment has started.',
              ),
              if (c.reviewBusy) ...[
                const SizedBox(height: 12),
                const LinearProgressIndicator(
                  semanticsLabel: 'Preparing simulation',
                ),
              ],
              if (checked) ...[
                const SizedBox(height: 12),
                Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    FilledButton.icon(
                      key: Key('hardware-run'),
                      onPressed: null,
                      icon: Icon(Icons.precision_manufacturing_outlined),
                      label: Text('Run on hardware'),
                    ),
                    FilledButton.icon(
                      key: const Key('confirm-run'),
                      onPressed: c.reviewBusy || c.dirty || !simulation
                          ? null
                          : c.runSimulation,
                      icon: c.startingSimulation
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.science_outlined),
                      label: Text(
                        c.startingSimulation ? 'Starting…' : 'Run simulation',
                      ),
                    ),
                    TextButton(
                      onPressed: c.reviewBusy ? null : c.cancelLaunch,
                      child: const Text('Cancel'),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  'Hardware execution is not available in this console yet.',
                ),
                Text(
                  simulation
                      ? 'Each simulation starts with a fresh declared load. Previous simulations do not consume its tips or liquids.'
                      : 'No simulation workstation is available.',
                ),
              ],
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              if (checked) ...[
                if (workflow != null)
                  ListTile(
                    title: Text(
                      workflow['enabled'] == true
                          ? 'Workflow simulation'
                          : 'Device validation',
                    ),
                    subtitle: Text(
                      internal.isEmpty
                          ? 'All planned device actions use the workstation.'
                          : 'The workstation runs the device actions. Internal simulation supplies ${internal.length} synthetic readout(s).',
                    ),
                  ),
                NativePreparationLayout(
                  key: ValueKey(
                    'preparation-layout-${c.inspection?['snapshot_id']}',
                  ),
                  plan: plan,
                  review: c.review,
                ),
                if (c.inspection?['source'] is String)
                  ExpansionTile(
                    title: const Text('Protocol steps'),
                    children: [SelectableText(c.inspection!['source'])],
                  ),
              ] else if (!c.reviewBusy) ...[
                Text(
                  c.message ?? 'Open the protocol again to repeat the checks.',
                ),
                if (c.messageDetails != null)
                  ExpansionTile(
                    title: const Text('Technical details'),
                    children: [SelectableText(c.messageDetails!)],
                  ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
