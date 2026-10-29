import 'package:flutter/material.dart';
import '../interactor/console_interactor.dart';
import '../model/console_model.dart';
import 'recorded_deck.dart';

/// A loading review and an explicit simulation action, never a hardware claim.
class NativeRunReviewView extends StatelessWidget {
  final NativeConsoleInteractor console;
  const NativeRunReviewView({super.key, required this.console});

  @override
  Widget build(BuildContext context) {
    final c = console;
    final preparation = c.inspection?['preparation'];
    final plan = preparation?['plan'] as Map? ?? {};
    final loadout = plan['loadout'] as List? ?? [];
    final supplies = plan['supplies'] as List? ?? [];
    final checked = c.launchReview != null;
    final simulation = c.review.simulationAvailable(c.station, c.inspection);
    final deck = RecordedDeck.fromLayout({
      'status': 'available',
      'layout': plan['layout'],
    });
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
                Text(
                  'What to prepare',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                Text(
                  loadout.isEmpty
                      ? 'A detailed loading plan is not available for this backend.'
                      : '${loadout.length} containers or plates · ${supplies.length} supply locations',
                ),
                const SizedBox(height: 8),
                const Text(
                  'For a hardware run, check the listed positions, container models, liquids and tips at the instrument. The OS cannot see whether they are physically present.',
                ),
                for (final item in loadout)
                  Card(
                    margin: const EdgeInsets.only(top: 12),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            c.review.location(item['placement']),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 6),
                          Text(
                            '${item['labware']} · ${item['model'] ?? 'Model not specified'}',
                          ),
                          const SizedBox(height: 8),
                          for (final vessel
                              in item['containers'] as List? ?? [])
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 3),
                              child: Text(
                                c.review.containerInstruction(vessel),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                if (supplies.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  Text(
                    'Tips and supplies',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  for (final supply in supplies)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.inventory_2_outlined),
                      title: Text(c.review.tipInstruction(supply)),
                    ),
                ],
                if (deck != null)
                  ExpansionTile(
                    key: const Key('review-deck'),
                    title: const Text('View planned deck layout'),
                    subtitle: const Text(
                      'Locations from the loading plan; not a live image of the instrument',
                    ),
                    children: [RecordedDeckBoard(deck: deck, keys: {})],
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
