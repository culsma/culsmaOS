import 'package:flutter/material.dart';
import '../../layout/view/layout_page.dart';
import '../../layout/view/instrument_settings.dart';
import '../../layout/view/floor_plan_editor.dart';
import '../../layout/view/floor_plan_board.dart';
import '../../layout/view/setup_header.dart';
import '../interactor/console_interactor.dart';
import '../model/console_model.dart';
import 'labware_dialog.dart';
import 'recorded_deck.dart';
import 'remote_access_settings.dart';
import 'execution_settings.dart';

class NativeSettingsView extends StatefulWidget {
  final NativeConsoleInteractor console;
  const NativeSettingsView({super.key, required this.console});
  @override
  State<NativeSettingsView> createState() => NativeSettingsViewState();
}

class NativeSettingsViewState extends State<NativeSettingsView> {
  bool advanced = false;
  bool requestedFloorPlan = false;
  String? selectedRack;
  Future<void> openInstrument(
    Map<String, dynamic> instrument,
    String? fingerprint,
    VoidCallback? editPlacement,
  ) async {
    final c = widget.console;
    final result = await showDialog<String>(
      context: context,
      builder: (context) => InstrumentSettingsDialog(
        controller: c.layout,
        instrument: instrument,
        fingerprint: fingerprint,
        canEdit: () =>
            !c.floorPlan.dirty &&
            !c.floorPlan.busy &&
            c.labware.pending == null,
        editPlacement: editPlacement,
      ),
    );
    if (!mounted) return;
    if (result == 'placement') editPlacement?.call();
    if (result == 'applied') {
      await c.refresh();
      if (!c.floorPlan.dirty) await c.floorPlan.submit('read');
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.console,
        deck = RecordedDeck.fromLayout(c.station?['layout']);
    final envelope = c.station?['layout'] as Map<String, dynamic>?;
    final fingerprint =
        envelope?['configuration_fingerprint'] as String? ??
        c.layout.active?['active']?['fingerprint'] as String?;
    final hasLayout = envelope?['status'] == 'available';
    final canPlan = hasLayout || c.station?['host']?['status'] == 'ready';
    if (canPlan && !requestedFloorPlan && c.floorPlan.plan == null) {
      requestedFloorPlan = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) c.floorPlan.submit('read');
      });
    }
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
    final simulationSettings = <Widget>[
      if (simulation is Map &&
          simulation['enabled'] is bool &&
          simulation['revision'] is int) ...[
        const Text(
          'Simulation',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
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
              : (enabled) =>
                    c.setWorkflowSimulation(enabled, simulation['revision']),
        ),
        const Divider(height: 32),
      ],
    ];
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
              OutlinedButton.icon(
                icon: Icon(advanced ? Icons.arrow_back : Icons.folder_open),
                onPressed:
                    (advanced && c.layout.dirty) ||
                        c.layout.busy ||
                        c.floorPlan.busy ||
                        c.layout.writeUncertain ||
                        c.layout.pendingRequest != null
                    ? null
                    : () => setState(() => advanced = !advanced),
                label: Text(advanced ? 'Workstation' : 'Saved setups'),
              ),
            ],
          ),
        ),
        Expanded(
          child: advanced
              ? editor
              : ListView(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                  children: [
                    ExecutionSettings(
                      controller: c.layout,
                      blocked:
                          c.working ||
                          c.floorPlan.dirty ||
                          c.floorPlan.busy ||
                          c.labware.pending != null,
                      onApplied: c.refresh,
                    ),
                    if (c.remoteAccess != null)
                      RemoteAccessSettings(controller: c.remoteAccess!),
                    if (deck == null) ...simulationSettings,
                    if (!hasLayout)
                      const Text(
                        'No rack layout is available for this workstation.',
                      ),
                    if (deck != null && selected != null) ...[
                      LayoutBuilder(
                        builder: (context, size) {
                          final selector = DropdownButtonFormField<String>(
                            key: ValueKey("installed-rack-${selected['id']}"),
                            initialValue: selected['id'],
                            isExpanded: true,
                            decoration: const InputDecoration(
                              labelText: 'Installed rack',
                            ),
                            items: [
                              for (final row in deck.carriers)
                                DropdownMenuItem<String>(
                                  value: row['id'],
                                  child: Text(
                                    "${row['id']} · track ${row['first'] ?? row['start'] + 1}",
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                            ],
                            onChanged: c.working
                                ? null
                                : (value) =>
                                      setState(() => selectedRack = value),
                          );
                          final replace = FilledButton.icon(
                            icon: const Icon(Icons.swap_horiz),
                            label: const Text('Replace rack…'),
                            onPressed: c.working
                                ? null
                                : () => showLabwareEditor(context, c, {
                                    'carrier': selected['id'],
                                    'model': selected['model'],
                                  }),
                          );
                          return size.maxWidth >= 550
                              ? Row(
                                  children: [
                                    Expanded(child: selector),
                                    const SizedBox(width: 12),
                                    replace,
                                  ],
                                )
                              : Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    selector,
                                    const SizedBox(height: 8),
                                    replace,
                                  ],
                                );
                        },
                      ),
                      const SizedBox(height: 16),
                      if (c.labware.message != null) Text(c.labware.message!),
                      if (c.labware.pending != null)
                        TextButton(
                          onPressed: c.labware.busy
                              ? null
                              : c.labware.checkStatus,
                          child: const Text('Check pending layout save'),
                        ),
                    ],
                    if (canPlan)
                      FutureBuilder<List<Map<String, dynamic>>>(
                        future: c.readInstruments(fingerprint),
                        builder: (context, snapshot) {
                          final instruments =
                              snapshot.connectionState == ConnectionState.done
                              ? snapshot.data ?? const <Map<String, dynamic>>[]
                              : const <Map<String, dynamic>>[];
                          final byId = {
                            for (final row in instruments) row['id']: row,
                          };
                          return Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (snapshot.hasError)
                                TextButton.icon(
                                  onPressed: () => setState(() {
                                    c.readInstruments(
                                      fingerprint,
                                      reload: true,
                                    );
                                  }),
                                  icon: const Icon(Icons.refresh),
                                  label: const Text(
                                    'Reload instrument settings',
                                  ),
                                ),
                              if (c.layout.pendingRequest != null)
                                TextButton(
                                  onPressed: c.layout.busy
                                      ? null
                                      : () async {
                                          await c.layout.inspectPending();
                                          await c.refresh();
                                          if (!c.floorPlan.dirty)
                                            await c.floorPlan.submit('read');
                                        },
                                  child: const Text(
                                    'Check pending configuration',
                                  ),
                                ),
                              if (instruments.isNotEmpty &&
                                  c.layout.message != null)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 8),
                                  child: Text(c.layout.message!),
                                ),
                              FloorPlanEditor(
                                controller: c.floorPlan,
                                instruments: instruments,
                                deck: FloorPlanDeck.fromLayout(envelope),
                                onRack: deck == null || c.working
                                    ? null
                                    : (id) {
                                        final rack = deck.carriers.firstWhere(
                                          (row) => row['id'] == id,
                                        );
                                        setState(() => selectedRack = id);
                                        showLabwareEditor(context, c, {
                                          'carrier': id,
                                          'model': rack['model'],
                                        });
                                      },
                                onInstrument: (item, editPlacement) {
                                  if (editPlacement == null) {
                                    openInstrument(item, fingerprint, null);
                                    return;
                                  }
                                  final device = byId[item['instrument']];
                                  final area = c.floorPlan
                                      .rows('areas')
                                      .where(
                                        (row) => row['id'] == item['area_id'],
                                      )
                                      .firstOrNull;
                                  openInstrument(
                                    {
                                      ...?device,
                                      'id': item['instrument'],
                                      'name': item['name'],
                                      'kind': item['kind'],
                                      'details': {
                                        if (area != null)
                                          'Workstation area': area['name'],
                                        if (item['handoff']
                                            case final String label)
                                          'Handoff label': label,
                                        ...?device?['details']
                                            as Map<String, dynamic>?,
                                      },
                                    },
                                    fingerprint,
                                    editPlacement,
                                  );
                                },
                                onApplied: c.refresh,
                              ),
                            ],
                          );
                        },
                      ),
                    if (deck != null && c.floorPlan.plan == null)
                      RecordedDeckBoard(deck: deck, keys: {}),
                    if (deck != null && simulationSettings.isNotEmpty) ...[
                      const Divider(height: 32),
                      ...simulationSettings,
                    ],
                  ],
                ),
        ),
      ],
    );
  }
}
