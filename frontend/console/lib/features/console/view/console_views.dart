import 'package:flutter/material.dart';
import '../../layout/model/layout_model.dart';
import '../../layout/view/layout_page.dart';
import 'settings_view.dart';
import 'evidence_panel.dart';
import '../interactor/console_interactor.dart';
import '../model/console_model.dart';
import 'labware_dialog.dart';
import 'recorded_deck.dart';
import 'setup_panel.dart';
import 'supply_panel.dart';
import 'run_control_panel.dart';
import 'system_information_view.dart';
import 'protocol_tree_view.dart';

class ConsoleViews extends StatelessWidget {
  final NativeConsoleInteractor console;
  final ConsoleWindowModel window;
  const ConsoleViews({super.key, required this.console, required this.window});
  @override
  Widget build(BuildContext context) => switch (window.view) {
    'files' => files(context),
    'workstation' => WorkstationRecords(console: console),
    'settings' => NativeSettingsView(console: console),
    'system_info' => NativeSystemInformationView(console: console),
    'experiment' => experiment(),
    _ => const Center(child: Text('Unsupported view')),
  };
  Widget heading(String title, [String? subtitle]) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        title,
        style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
      ),
      if (subtitle != null) ...[
        const SizedBox(height: 8),
        Text(subtitle, style: const TextStyle(color: Color(0xff62798c))),
      ],
      const SizedBox(height: 20),
    ],
  );
  Widget files(BuildContext context) {
    final c = console, items = c.library?['programs'] as List? ?? [];
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        heading(
          'Files',
          c.library?['source_root']?.toString() ??
              'Reading the local program directory…',
        ),
        Row(
          children: [
            OutlinedButton.icon(
              onPressed: c.busy ? null : c.refreshFiles,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('Refresh files'),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (c.pendingStart != null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'An unresolved run request is retained. No automatic repeat.',
                  ),
                  TextButton(
                    onPressed: c.busy ? null : c.checkPendingStart,
                    child: const Text('Check retained run request'),
                  ),
                ],
              ),
            ),
          ),
        if (items.isEmpty)
          const Text('Add .culs files to the program directory, then refresh.'),
        NativeProtocolTree(
          programs: items,
          selected: c.selectedFile,
          busy: c.busy || c.pendingStart != null,
          inspect: c.inspectFile,
          run: c.launch,
        ),
        if (c.inspection != null) ...[
          const Divider(height: 32),
          heading(c.selectedFile ?? 'Protocol'),
          Text(
            c.inspection!['valid'] == true
                ? 'Source validated'
                : 'Source validation failed',
          ),
          ExpansionTile(
            title: const Text('Protocol source'),
            children: [
              Padding(
                padding: const EdgeInsets.all(12),
                child: SelectableText(
                  c.inspection!['source']?.toString() ?? 'Source unavailable',
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }

  Widget experiment() {
    final run = console.runs[window.entityId];
    if (run == null)
      return const Center(child: Text('Reading the experiment record…'));
    final result = run['result'] as Map? ?? {},
        record = result['os']?['registered_material'];
    final containers = record?['state']?['containers'] as Map? ?? {};
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        heading('Experiment ${run['status']}', window.entityId),
        if (run['error'] != null)
          Text(run['error'], style: const TextStyle(color: Color(0xff924e25))),
        NativeRunControlPanel(controller: console.controls, run: run),
        if (run['status'] == 'awaiting_setup')
          NativeSetupPanel(controller: console.setup, run: run),
        if (result['execution'] != null)
          Text(
            '${result['execution']['completed_steps']} / ${result['execution']['total_steps']} semantic steps completed',
          ),
        const SizedBox(height: 24),
        const Text(
          'OS-registered material',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        if (containers.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: Text('No registered material snapshot is available.'),
          ),
        for (final row in containers.entries)
          ListTile(
            title: Text(row.value['metadata']?['allocation_name'] ?? row.key),
            subtitle: Text(
              '${row.value['metadata']?['kind'] ?? 'Container'} · model state',
            ),
            trailing: Text('${row.value['volume_uL']} µL'),
          ),
        const Text(
          'Registered quantities are OS model state, not physical measurements.',
          style: TextStyle(color: Color(0xff62798c)),
        ),
        const SizedBox(height: 20),
        NativeEvidencePanel(run: run),
        if (run['status'] != 'awaiting_setup' &&
            console.setup.plans[window.entityId] != null)
          ExpansionTile(
            key: ValueKey('loading-history-${window.entityId}'),
            title: const Text('Recorded loading plan'),
            subtitle: const Text(
              'Preparation record; the execution outcome is shown above',
            ),
            children: [NativeSetupPanel(controller: console.setup, run: run)],
          ),
      ],
    );
  }
}

class WorkstationRecords extends StatefulWidget {
  final NativeConsoleInteractor console;
  const WorkstationRecords({super.key, required this.console});
  @override
  State<WorkstationRecords> createState() => WorkstationRecordsState();
}

class WorkstationRecordsState extends State<WorkstationRecords> {
  final keys = <String, GlobalKey>{};
  @override
  void initState() {
    super.initState();
    widget.console.revealTarget = reveal;
  }

  Future<void> edit(BuildContext context, Map<String, dynamic> desired) =>
      showLabwareEditor(context, widget.console, desired);

  bool equipmentOpen = false;
  Future<bool> reveal(String id) async {
    if (keys[id]?.currentContext == null && mounted) {
      setState(() => equipmentOpen = true);
      await WidgetsBinding.instance.endOfFrame;
    }
    String? slot;
    final envelope = widget.console.station?['layout'];
    if (envelope?['layout']?['definition']?['schema'] == 'culsma_layout_v1') {
      final raw = envelope['layout'];
      try {
        slot =
            LayoutDefinition(
              Map<String, dynamic>.from(raw['definition']),
              Map<String, dynamic>.from(raw['configuration']),
            ).presentationPosition(
              Map<String, dynamic>.from(raw['configuration']),
              id,
            );
      } catch (_) {
        return false;
      }
    }
    final context = keys[id]?.currentContext ?? keys[slot]?.currentContext;
    if (context == null) return false;
    await Scrollable.ensureVisible(
      context,
      alignment: .5,
      duration: const Duration(milliseconds: 150),
    );
    return mounted;
  }

  Future<void> inspectSlot(
    BuildContext context,
    LayoutDefinition definition,
    Map<String, dynamic> configuration,
    String id,
  ) async {
    final all = definition.items(configuration),
        root = definition.occupant(configuration, id);
    final values = all
        .where(
          (item) =>
              definition.footprint(item).contains(id) ||
              (root != null && item.parent == root.name),
        )
        .toList();
    if (values.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'This declared position is empty. Use System Settings for supported layout changes.',
          ),
        ),
      );
      return;
    }
    LayoutItem? selected;
    if (values.length == 1)
      selected = values.single;
    else
      selected = await showDialog<LayoutItem>(
        context: context,
        builder: (context) => SimpleDialog(
          title: Text('Configured items · position $id'),
          children: [
            for (final item in values)
              SimpleDialogOption(
                onPressed: () => Navigator.pop(context, item),
                child: Text('${item.name} · ${item.model}'),
              ),
          ],
        ),
      );
    if (selected != null && context.mounted)
      await edit(context, {'item': selected.name, 'model': selected.model});
  }

  Widget outsideEquipment(
    BuildContext context,
    Map<String, dynamic>? envelope,
  ) {
    final definition = envelope?['layout']?['definition'],
        groups = definition?['diagram']?['groups'] as List? ?? [];
    if (groups.isEmpty) return const SizedBox.shrink();
    final objects = {
      for (final item in definition?['objects'] as List? ?? [])
        item['id']: item,
    };
    return ExpansionTile(
      key: ValueKey('outside-equipment-$equipmentOpen'),
      initiallyExpanded: equipmentOpen,
      onExpansionChanged: (value) => equipmentOpen = value,
      title: const Text(
        'Fixed equipment and placements outside the track deck',
      ),
      children: [
        for (final group in groups) ...[
          ListTile(title: Text(group['label'] ?? 'Configured equipment')),
          for (final id in group['objects'] as List? ?? [])
            if (objects[id] != null)
              ListTile(
                key: keys.putIfAbsent(id, () => GlobalKey()),
                title: Text(id),
                subtitle: Text(
                  objects[id]['model'] ?? 'Declared layout object',
                ),
                selected: widget.console.selectedEntity == id,
                onTap: () =>
                    edit(context, {'item': id, 'model': objects[id]['model']}),
              ),
        ],
      ],
    );
  }

  @override
  void dispose() {
    widget.console.revealTarget = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.console,
        envelope = c.station?['layout'] as Map<String, dynamic>?,
        deck = RecordedDeck.fromLayout(envelope);
    Widget board = const Text(
      'The driver does not provide a supported layout projection.',
    );
    if (deck != null)
      board = RecordedDeckBoard(
        deck: deck,
        keys: keys,
        selectedEntity: c.selectedEntity,
        onItem: (item) =>
            edit(context, {'item': item['id'], 'model': item['model']}),
        onSite: (parent, site) =>
            edit(context, {'parent': parent, 'site': site}),
      );
    else if (envelope?['layout']?['definition']?['schema'] ==
        'culsma_layout_v1') {
      try {
        final raw = envelope!['layout'],
            definition = LayoutDefinition(
              Map<String, dynamic>.from(raw['definition']),
              Map<String, dynamic>.from(raw['configuration']),
            );
        board = DeckBoard(
          definition: definition,
          positionKeys: keys,
          configuration: raw['configuration'],
          selected: null,
          enabled: true,
          onSelect: (id) => inspectSlot(
            context,
            definition,
            Map<String, dynamic>.from(raw['configuration']),
            id,
          ),
        );
      } catch (_) {
        board = const Text('Layout projection is unavailable.');
      }
    }
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Text(
          'Workstation',
          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        Text(
          'Station: ${c.station?['host']?['status'] ?? 'Reading…'} · declared geometry',
        ),
        const SizedBox(height: 20),
        NativeSupplyPanel(console: c),
        board,
        outsideEquipment(context, envelope),
        const SizedBox(height: 16),
        const Text(
          'Click a position to place, replace or remove its contents. No physical loading is inferred.',
        ),
        if (c.labware.message != null) Text(c.labware.message!),
        if (c.labware.error != null && !c.labware.editing)
          Text(c.labware.error!),
        if (c.labware.pending != null)
          TextButton(
            onPressed: c.labware.busy ? null : c.labware.checkStatus,
            child: const Text('Check pending layout save'),
          ),
        const SizedBox(height: 24),
        const Text(
          'Runs and history',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        for (final run in c.station?['runs'] as List? ?? [])
          ListTile(
            title: Text(run['run_id']),
            subtitle: Text(run['status']),
            onTap: () {
              c.open('experiment', run['run_id']);
              c.refresh();
            },
          ),
      ],
    );
  }
}
