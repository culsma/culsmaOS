import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../interactor/floor_plan_controller.dart';
import 'floor_plan_board.dart';

const _kinds = {
  'centrifuge': 'Centrifuge',
  'incubator': 'Incubator',
  'washer': 'Plate washer',
  'dispenser': 'Dispenser',
  'shaker': 'Shaker',
  'magnet': 'Magnetic rack',
  'temperature': 'Temperature module',
  'vortexer': 'Vortexer',
  'other': 'Other instrument',
};

enum _AreaAction { add, edit }

class FloorPlanEditor extends StatefulWidget {
  const FloorPlanEditor({
    super.key,
    required this.controller,
    required this.deck,
    required this.onApplied,
    this.onRack,
    this.onInstrument,
    this.instruments = const [],
  });
  final FloorPlanController controller;
  final FloorPlanDeck deck;
  final Future<void> Function() onApplied;
  final ValueChanged<String>? onRack;
  final List<Map<String, dynamic>> instruments;
  final void Function(Map<String, dynamic> item, VoidCallback? editPlacement)?
  onInstrument;

  @override
  State<FloorPlanEditor> createState() => _FloorPlanEditorState();
}

class _FloorPlanEditorState extends State<FloorPlanEditor> {
  String level = 'deck';
  FloorPlanController get controller => widget.controller;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final areas = c.rows('areas');
    final equipment = c.rows('equipment');
    final metric = c.plan?['deck'] != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Workstation layout',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 6),
        const Text(
          'Click a device to configure it, or click an empty spot in an area to add one.',
        ),
        if (c.busy) const LinearProgressIndicator(),
        if (c.message != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Semantics(liveRegion: true, child: Text(c.message!)),
          ),
        if (c.plan != null) ...[
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            children: [
              OutlinedButton(
                onPressed: c.editable ? () => editDeck(context) : null,
                child: Text(
                  metric
                      ? "${c.plan!['deck']['width']} × ${c.plan!['deck']['height']} mm · Deck bounds"
                      : 'Set deck bounds',
                ),
              ),
              DropdownButton<String>(
                value: level,
                items: [
                  for (final entry in floorLevels.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    ),
                ],
                onChanged: (value) => setState(() => level = value!),
              ),
            ],
          ),
          FloorPlanBoard(
            plan: c.plan!,
            deck: widget.deck,
            level: level,
            instruments: widget.instruments,
            onMountedInstrument: widget.onInstrument == null
                ? null
                : (device) => widget.onInstrument!(device, null),
            onRack: widget.onRack,
            onArea: c.editable ? openArea : null,
            onEquipment: c.editable
                ? (id) {
                    final item = equipment.firstWhere((row) => row['id'] == id);
                    void editPlacement() => edit(context, 'equipment', item);
                    if (widget.onInstrument != null) {
                      widget.onInstrument!(item, editPlacement);
                    } else {
                      editPlacement();
                    }
                  }
                : null,
            onDrop: c.editable && metric ? moveEquipment : null,
          ),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final side
                  in level == 'deck'
                      ? ['Rear', 'Right', 'Front', 'Left']
                      : ['Area'])
                OutlinedButton.icon(
                  onPressed: c.editable && metric
                      ? () => edit(context, 'areas', null, side)
                      : null,
                  icon: const Icon(Icons.add),
                  label: Text(
                    side == 'Area'
                        ? 'Add area'
                        : 'Add ${side.toLowerCase()} area',
                  ),
                ),
            ],
          ),
        ],
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (c.uncertain || c.plan == null)
              TextButton(
                onPressed: c.busy ? null : () => c.submit('read'),
                child: const Text('Reload saved layout'),
              ),
            if (c.dirty && !c.uncertain)
              TextButton(
                onPressed: c.editable ? c.discard : null,
                child: const Text('Discard edits'),
              ),
            OutlinedButton(
              onPressed: c.editable && c.dirty ? () => c.submit('save') : null,
              child: const Text('Save draft'),
            ),
            OutlinedButton(
              onPressed:
                  c.editable &&
                      !c.dirty &&
                      (c.state?['revision'] as int? ?? 0) > 0
                  ? () => c.submit('check')
                  : null,
              child: const Text('Check layout'),
            ),
            FilledButton(
              onPressed: c.editable && !c.dirty && c.checked
                  ? () async {
                      if (await c.submit('apply')) await widget.onApplied();
                    }
                  : null,
              child: const Text('Apply layout'),
            ),
          ],
        ),
      ],
    );
  }

  Future<void> editDeck(BuildContext context) async {
    final existing = controller.plan?['deck'];
    final suggested = widget.deck.suggestedSize;
    final form = GlobalKey<FormState>();
    final size = <String, dynamic>{
      'width': existing?['width'] ?? suggested?.width.ceil(),
      'height': existing?['height'] ?? suggested?.height.ceil(),
    };
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Deck bounds'),
        scrollable: true,
        content: Form(
          key: form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 16,
            children: [
              const Text(
                'Use the rear-left corner as the origin. Confirm the physical size of the working deck.',
              ),
              _number(
                size,
                'width',
                'Width (mm)',
                min: suggested?.width.ceil() ?? 1,
              ),
              _number(
                size,
                'height',
                'Depth (mm)',
                min: suggested?.height.ceil() ?? 1,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (!form.currentState!.validate()) return;
              form.currentState!.save();
              Navigator.pop(context, true);
            },
            child: const Text('Done'),
          ),
        ],
      ),
    );
    if (result == true && mounted)
      controller.setDeck(size['width'], size['height']);
  }

  Future<void> openArea(String areaId, Offset position) async {
    if (controller.plan?['deck'] == null) {
      await editDeck(context);
      return;
    }
    final area = controller
        .rows('areas')
        .firstWhere((row) => row['id'] == areaId);
    final action = await showDialog<_AreaAction>(
      context: context,
      builder: (context) => SimpleDialog(
        title: Text(area['name']),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, _AreaAction.add),
            child: const ListTile(
              leading: Icon(Icons.add),
              title: Text('Add instrument'),
            ),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, _AreaAction.edit),
            child: const ListTile(
              leading: Icon(Icons.edit_outlined),
              title: Text('Edit area'),
            ),
          ),
        ],
      ),
    );
    if (!mounted || !controller.editable) return;
    if (action == _AreaAction.edit) {
      await edit(context, 'areas', area);
    } else if (action == _AreaAction.add) {
      await addInstrument(area, position);
    }
  }

  Future<void> addInstrument(Map<String, dynamic> area, Offset position) async {
    final placed = {
      for (final item in controller.rows('equipment')) item['instrument'],
    };
    final available = placeableInstruments().where(
      (row) => !placed.contains(row['id']),
    );
    final selected = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('Add instrument'),
        children: [
          if (available.isNotEmpty) ...[
            const ListTile(title: Text('Available workstation devices')),
            for (final row in available)
              SimpleDialogOption(
                onPressed: () => Navigator.pop(context, {
                  'instrument': row['id'],
                  'kind': row['kind'],
                  'name': row['name'],
                }),
                child: ListTile(
                  leading: Icon(floorPlanIcon(row['kind'])),
                  title: Text(row['name']),
                ),
              ),
            const Divider(),
          ],
          const ListTile(title: Text('Add by device type')),
          for (final entry in _kinds.entries)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, {
                'kind': entry.key,
                'name': entry.value,
              }),
              child: ListTile(
                leading: Icon(floorPlanIcon(entry.key)),
                title: Text(entry.value),
              ),
            ),
        ],
      ),
    );
    if (selected == null || !mounted || !controller.editable) return;
    await edit(context, 'equipment', null, 'Rear', {
      ...selected,
      'area_id': area['id'],
      'x': position.dx.round().clamp(0, (area['width'] as int) - 1),
      'y': position.dy.round().clamp(0, (area['height'] as int) - 1),
    });
  }

  void moveEquipment(String areaId, String itemId, Offset position) {
    final area = controller
        .rows('areas')
        .firstWhere((row) => row['id'] == areaId);
    final items = controller.rows('equipment');
    final item = items.where((item) => item['id'] == itemId).firstOrNull;
    if (item == null) return;
    final maxX = (area['width'] as int) - ((item['width'] as int?) ?? 0);
    final maxY = (area['height'] as int) - ((item['height'] as int?) ?? 0);
    if (maxX < 0 || maxY < 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('This area is smaller than the instrument.'),
        ),
      );
      return;
    }
    controller.update('equipment', [
      for (final row in items)
        if (row['id'] == itemId)
          {
            ...row,
            'area_id': areaId,
            'x': position.dx.round().clamp(0, maxX),
            'y': position.dy.round().clamp(0, maxY),
          }
        else
          row,
    ]);
  }

  List<Map<String, dynamic>> placeableInstruments() {
    final settings = {for (final row in widget.instruments) row['id']: row};
    return [
      for (final row in List<Map<String, dynamic>>.from(
        controller.state?['instruments'] ?? [],
      ))
        if (!widget.deck.hasMount(settings[row['id']] ?? row))
          {...row, 'name': settings[row['id']]?['name'] ?? row['name']},
    ];
  }

  Future<void> edit(
    BuildContext context,
    String key, [
    Map<String, dynamic>? item,
    String side = 'Rear',
    Map<String, dynamic> placement = const {},
  ]) async {
    final areas = controller.rows('areas');
    final isArea = key == 'areas';
    final id = item?['id'] ?? DateTime.now().microsecondsSinceEpoch.toString();
    final deck = controller.plan?['deck'] as Map?;
    if (deck == null) {
      await editDeck(context);
      return;
    }
    final width = deck['width'] as int, depth = deck['height'] as int;
    final layer = areas.where((area) => area['level'] == level).toList();
    final span = math.max(1, (width * .3).round());
    final strip = math.max(1, (depth * .3).round());
    final left = layer.fold(0, (x, a) => math.min(x, a['x'] as int));
    final rear = layer.fold(0, (y, a) => math.min(y, a['y'] as int));
    final right = layer.fold(
      width,
      (x, a) => math.max(x, (a['x'] as int) + (a['width'] as int)),
    );
    final front = layer.fold(
      depth,
      (y, a) => math.max(y, (a['y'] as int) + (a['height'] as int)),
    );
    final initial =
        item ??
        (isArea
            ? {
                'id': id,
                'name': side == 'Area' ? floorLevels[level] : '$side extension',
                'level': level,
                'x': side == 'Left'
                    ? left - span
                    : side == 'Right'
                    ? right
                    : 0,
                'y': side == 'Rear'
                    ? rear - strip
                    : side == 'Front' || (side == 'Area' && layer.isNotEmpty)
                    ? front
                    : 0,
                'width': side == 'Left' || side == 'Right' ? span : width,
                'height': side == 'Left' || side == 'Right' || side == 'Area'
                    ? depth
                    : strip,
              }
            : {
                'id': id,
                'name': '',
                'kind': 'other',
                'area_id': layer.first['id'],
                'x': 0,
                'y': 0,
                'width': null,
                'height': null,
                'instrument': null,
                'handoff': null,
                ...placement,
              });
    final equipment = controller.rows('equipment');
    final used = {
      for (final row in equipment)
        if (row['id'] != id) row['instrument'],
    };
    final instruments = [
      for (final row in placeableInstruments())
        if (!used.contains(row['id']) &&
            (item == null || row['kind'] == item['kind']))
          row,
    ];
    final binding = initial['instrument'];
    final fixedInstrument = binding == null
        ? null
        : [
                    ...instruments,
                    ...widget.instruments,
                  ].where((row) => row['id'] == binding).firstOrNull?['name']
                  as String? ??
              initial['name'] as String;
    final result = await showDialog<Object>(
      context: context,
      builder: (context) => _PlacementDialog(
        area: isArea,
        initial: initial,
        areas: areas,
        instruments: item == null ? const [] : instruments,
        fixedInstrument: fixedInstrument,
        existing: item != null,
        removable:
            item != null &&
            (!isArea || !equipment.any((row) => row['area_id'] == id)),
      ),
    );
    if (result == null || !context.mounted) return;
    if (result == _PlacementAction.remove) {
      controller.update(
        key,
        controller.rows(key).where((row) => row['id'] != id).toList(),
      );
      return;
    }
    final updated = result as Map<String, dynamic>;
    controller.update(key, [
      for (final row in controller.rows(key))
        if (row['id'] == id) updated else row,
      if (item == null) updated,
    ]);
    if (isArea) setState(() => level = updated['level']);
  }
}

Widget _number(
  Map<String, dynamic> value,
  String key,
  String label, {
  int? min,
}) => TextFormField(
  initialValue: value[key]?.toString(),
  decoration: InputDecoration(labelText: label),
  keyboardType: TextInputType.numberWithOptions(signed: min == null),
  validator: (text) {
    final number = int.tryParse(text ?? '');
    if (number == null ||
        number.abs().bitLength > 53 ||
        (min != null && number < min)) {
      return min == null
          ? 'Enter a whole number'
          : 'Enter a whole number of at least $min';
    }
    return null;
  },
  onSaved: (text) => value[key] = int.parse(text!),
);

enum _PlacementAction { remove }

class _PlacementDialog extends StatefulWidget {
  const _PlacementDialog({
    required this.area,
    required this.initial,
    required this.areas,
    required this.instruments,
    required this.fixedInstrument,
    required this.existing,
    required this.removable,
  });
  final bool area, existing, removable;
  final String? fixedInstrument;
  final Map<String, dynamic> initial;
  final List<Map<String, dynamic>> areas, instruments;

  @override
  State<_PlacementDialog> createState() => _PlacementDialogState();
}

class _PlacementDialogState extends State<_PlacementDialog> {
  final form = GlobalKey<FormState>();
  late final value = Map<String, dynamic>.from(widget.initial);
  late final name = TextEditingController(text: value['name']);

  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isArea = widget.area;
    final instrument = value['instrument'] as String?;
    final configured =
        widget.fixedInstrument != null ||
        widget.instruments.any((row) => row['id'] == instrument);
    return AlertDialog(
      title: Text(isArea ? 'Expansion area' : 'Instrument placement'),
      actionsPadding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
      content: SizedBox(
        width: 390,
        child: SingleChildScrollView(
          padding: const EdgeInsets.only(top: 8),
          child: Form(
            key: form,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              spacing: 16,
              children: [
                if (!isArea) ...[
                  if (widget.fixedInstrument case final String name)
                    InputDecorator(
                      decoration: const InputDecoration(
                        labelText: 'Station instrument',
                      ),
                      child: Text(name),
                    )
                  else if (widget.instruments.isNotEmpty)
                    DropdownButtonFormField<String>(
                      initialValue: configured ? instrument : '',
                      isExpanded: true,
                      decoration: const InputDecoration(
                        labelText: 'Station control',
                      ),
                      items: [
                        const DropdownMenuItem(
                          value: '',
                          child: Text('No control selected'),
                        ),
                        for (final row in widget.instruments)
                          DropdownMenuItem(
                            value: row['id'],
                            child: Text(
                              "${row['name']} · ${row['kind']}",
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                      ],
                      onChanged: (id) => setState(() {
                        final row = widget.instruments
                            .where((row) => row['id'] == id)
                            .firstOrNull;
                        value['instrument'] = row?['id'];
                        if (row != null) {
                          value['kind'] = row['kind'];
                          if (name.text.trim().isEmpty) name.text = row['name'];
                        }
                      }),
                    ),
                  if (!configured && !widget.existing)
                    DropdownButtonFormField<String>(
                      initialValue: value['kind'],
                      decoration: const InputDecoration(labelText: 'Type'),
                      items: [
                        for (final entry in _kinds.entries)
                          DropdownMenuItem(
                            value: entry.key,
                            child: Text(entry.value),
                          ),
                      ],
                      onChanged: (kind) => setState(() => value['kind'] = kind),
                    ),
                  DropdownButtonFormField<String>(
                    initialValue: value['area_id'],
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Area'),
                    items: [
                      for (final area in widget.areas)
                        DropdownMenuItem(
                          value: area['id'],
                          child: Text(
                            area['name'],
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: (id) => value['area_id'] = id,
                  ),
                ],
                TextFormField(
                  controller: name,
                  decoration: const InputDecoration(labelText: 'Name'),
                  maxLength: 80,
                  validator: (text) => text == null || text.trim().isEmpty
                      ? 'Enter a name'
                      : null,
                  onSaved: (text) => value['name'] = text!.trim(),
                ),
                if (isArea)
                  DropdownButtonFormField<String>(
                    initialValue: value['level'],
                    decoration: const InputDecoration(labelText: 'Level'),
                    items: [
                      for (final entry in floorLevels.entries)
                        DropdownMenuItem(
                          value: entry.key,
                          child: Text(entry.value),
                        ),
                    ],
                    onChanged: (level) => value['level'] = level,
                  ),
                _number(
                  value,
                  'x',
                  isArea ? 'X from deck (mm)' : 'X within area (mm)',
                  min: isArea ? null : 0,
                ),
                _number(
                  value,
                  'y',
                  isArea ? 'Y from deck (mm)' : 'Y within area (mm)',
                  min: isArea ? null : 0,
                ),
                _number(value, 'width', 'Width (mm)', min: 1),
                _number(value, 'height', 'Depth (mm)', min: 1),
                if (!isArea)
                  TextFormField(
                    initialValue: value['handoff'],
                    decoration: const InputDecoration(
                      labelText: 'Handoff label (optional)',
                    ),
                    maxLength: 80,
                    onSaved: (text) =>
                        value['handoff'] = text == null || text.trim().isEmpty
                        ? null
                        : text.trim(),
                  ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        if (widget.removable)
          TextButton(
            onPressed: () => Navigator.pop(context, _PlacementAction.remove),
            child: const Text('Remove from layout'),
          ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            if (!form.currentState!.validate()) return;
            form.currentState!.save();
            if (!isArea && !configured) value['instrument'] = null;
            Navigator.pop(context, value);
          },
          child: const Text('Done'),
        ),
      ],
    );
  }
}
