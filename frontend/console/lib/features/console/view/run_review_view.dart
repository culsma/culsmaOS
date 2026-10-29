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
                c.submittingRun
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
              const Text(
                'Review the loading plan below. No experiment has started.',
              ),
              if (c.reviewBusy) const LinearProgressIndicator(),
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
                      icon: const Icon(Icons.science_outlined),
                      label: const Text('Run simulation'),
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
                      ? 'Simulation uses the current simulated inventory. It does not move hardware or confirm physical loading.'
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
