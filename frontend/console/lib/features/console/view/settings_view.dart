import 'package:flutter/material.dart';
import '../../layout/view/layout_page.dart';
import '../../layout/view/setup_header.dart';
import '../interactor/console_interactor.dart';
import '../model/console_model.dart';
import 'labware_dialog.dart';
import 'recorded_deck.dart';

class NativeSettingsView extends StatefulWidget {
  final NativeConsoleInteractor console;
  const NativeSettingsView({super.key, required this.console});
  @override
  State<NativeSettingsView> createState() => NativeSettingsViewState();
}

class NativeSettingsViewState extends State<NativeSettingsView> {
  bool advanced = false;
  String? selectedRack;
  @override
  Widget build(BuildContext context) {
    final c = widget.console,
        deck = RecordedDeck.fromLayout(c.station?['layout']);
    final editor = Column(
      children: [
        SetupHeader(controller: c.layout),
        Expanded(child: LayoutPage(controller: c.layout)),
      ],
    );

    final selected =
        deck?.carriers.where((row) => row['id'] == selectedRack).firstOrNull ??
        deck?.carriers.firstOrNull;
    final simulation = c.station?['host']?['workflow_simulation'];
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'System Settings',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
                ),
              ),
              TextButton(
                onPressed:
                    c.layout.dirty ||
                        c.layout.busy ||
                        c.layout.writeUncertain ||
                        c.layout.pendingRequest != null
                    ? null
                    : () => setState(() => advanced = !advanced),
                child: Text(
                  advanced ? 'Rack settings' : 'Advanced layout editor',
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: advanced
              ? editor
              : ListView(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                  children: [
                    if (simulation is Map &&
                        simulation['enabled'] is bool &&
                        simulation['revision'] is int) ...[
                      const Text(
                        'Simulation',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      SwitchListTile(
                        key: const Key('enable-workflow-simulation'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Enable workflow simulation'),
                        subtitle: const Text(
                          'Use configured internal models for supported missing steps in new simulations. With this off, the workstation must support every step.',
                        ),
                        value: simulation['enabled'],
                        onChanged: c.working
                            ? null
                            : (enabled) => c.setWorkflowSimulation(
                                enabled,
                                simulation['revision'],
                              ),
                      ),
                      const Divider(height: 32),
                    ],
                    if (deck == null)
                      const Text(
                        'No rack layout is available for this workstation.',
                      )
                    else ...[
                      const Text(
                        'Racks and carriers',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Replace the installed rack model here. Change the containers on its positions in Workstation. Compatibility choices come from the installed driver.',
                      ),
                      const SizedBox(height: 20),
                      if (selected != null) ...[
                        DropdownButtonFormField<String>(
                          key: ValueKey('installed-rack-${selected['id']}'),
                          initialValue: selected['id'],
                          isExpanded: true,
                          decoration: const InputDecoration(
                            labelText: 'Installed rack',
                          ),
                          items: deck.carriers
                              .map(
                                (row) => DropdownMenuItem<String>(
                                  value: row['id'],
                                  child: Text(
                                    '${row['id']} · track ${row['first'] ?? row['start'] + 1}',
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              )
                              .toList(),
                          onChanged: c.working
                              ? null
                              : (value) => setState(() => selectedRack = value),
                        ),
                        const SizedBox(height: 12),
                        Text('Current model: ${selected['model']}'),
                        const SizedBox(height: 12),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: FilledButton.icon(
                            icon: const Icon(Icons.swap_horiz),
                            label: const Text('Replace rack…'),
                            onPressed: c.working
                                ? null
                                : () => showLabwareEditor(context, c, {
                                    'carrier': selected['id'],
                                    'model': selected['model'],
                                  }),
                          ),
                        ),
                      ],
                      const SizedBox(height: 20),
                      RecordedDeckBoard(deck: deck, keys: {}),
                      const SizedBox(height: 20),
                      if (c.labware.message != null) Text(c.labware.message!),
                      if (c.labware.pending != null)
                        TextButton(
                          onPressed: c.labware.busy
                              ? null
                              : c.labware.checkStatus,
                          child: const Text('Check pending layout save'),
                        ),
                    ],
                  ],
                ),
        ),
      ],
    );
  }
}
