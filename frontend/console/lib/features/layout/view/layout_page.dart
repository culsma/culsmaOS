import 'track_board.dart';
import 'configuration_fields.dart';
import 'dart:math';
import 'package:flutter/material.dart';
import '../interactor/layout_controller.dart';
import '../model/layout_model.dart';

class LayoutPage extends StatefulWidget {
  final LayoutController controller;
  const LayoutPage({super.key, required this.controller});
  @override
  State<LayoutPage> createState() => LayoutPageState();
}

class LayoutPageState extends State<LayoutPage> {
  final name = TextEditingController(text: 'labware_1');
  String? model;
  String? childModel, childSite;
  String? lastPosition, lastDefinitionId;
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    LayoutDefinition? definition;
    String? definitionError;
    try {
      definition = c.definition;
      definition?.items(c.proposal!);
    } on FormatException catch (error) {
      definition = null;
      definitionError = error.message.toString();
    } catch (_) {
      definition = null;
      definitionError = 'LAYOUT_DEFINITION_INVALID';
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'Layout',
                  style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600),
                ),
              ),
              Text(
                c.profile?['activation_supported'] == false
                    ? 'Offline proposal'
                    : c.active?['host']?['status'] ?? 'Connecting',
                key: const Key('station-state'),
              ),
              Semantics(
                label: 'Refresh station status',
                child: IconButton(
                  tooltip: 'Refresh station status',
                  onPressed: c.busy ? null : c.load,
                  icon: const Icon(Icons.refresh),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            c.draft == null
                ? 'Select a saved setup to prepare a layout.'
                : '${c.draft!['title']} · revision ${c.draft!['revision']}',
          ),
          if (c.draft != null)
            Text(
              c.active?['active']?['origin']?['draft_id'] ==
                          c.draft!['draft_id'] &&
                      c.active?['active']?['origin']?['revision'] ==
                          c.draft!['revision']
                  ? 'Editing the current saved setup.'
                  : 'Proposed setup; the active station is unchanged.',
            ),
          if (c.draft == null && c.drafts.isNotEmpty) ...[
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              decoration: const InputDecoration(labelText: 'Saved setup'),
              items: c.drafts
                  .map(
                    (d) => DropdownMenuItem<String>(
                      value: d['draft_id'],
                      child: Text(d['title']),
                    ),
                  )
                  .toList(),
              onChanged: c.busy
                  ? null
                  : (id) {
                      if (id != null) c.openDraft(id);
                    },
            ),
          ],
          if (c.draft == null) ...[
            const SizedBox(height: 16),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: c.profiles
                  .where((p) => p['layout'] != null)
                  .map(
                    (p) => OutlinedButton(
                      onPressed: c.busy || c.writeUncertain
                          ? null
                          : () => c.createSetup(p),
                      child: Text('Prepare setup: ${p['label']}'),
                    ),
                  )
                  .toList(),
            ),
          ],
          if (c.busy)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: LinearProgressIndicator(),
            ),
          if (c.message != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Semantics(
                liveRegion: true,
                child: Text(c.message!, key: const Key('operation-result')),
              ),
            ),
          const SizedBox(height: 20),
          if (definition != null) ...[
            ConfigurationFields(controller: c),
            const SizedBox(height: 20),
            Text(
              '${definition.label} · schematic${definition.variant['presentation'] == 'tracks' ? ' · scroll horizontally' : ''}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            LayoutBuilder(
              builder: (context, constraints) {
                final board = DeckBoard(
                  definition: definition!,
                  configuration: c.proposal!,
                  selected: c.selectedPosition,
                  enabled:
                      !c.busy && !c.writeUncertain && c.pendingRequest == null,
                  onSelect: c.selectPosition,
                );
                final panel = Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: const Color(0xffdce3ec)),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: inspector(context, definition),
                );
                if (constraints.maxWidth < 760)
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [board, const SizedBox(height: 20), panel],
                  );
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(flex: 3, child: board),
                    const SizedBox(width: 24),
                    Expanded(flex: 2, child: panel),
                  ],
                );
              },
            ),
            const SizedBox(height: 16),
            const Text(
              'Edits prepare a layout. They do not move physical labware. Driver validation and device preflight remain authoritative.',
            ),
            if (c.profile?['activation_supported'] == false) ...[
              const SizedBox(height: 12),
              const Text(
                'Offline layout planning. Save and check proposals; hardware application is unavailable.',
              ),
            ],
            const SizedBox(height: 20),
            Wrap(
              spacing: 12,
              runSpacing: 10,
              children: [
                OutlinedButton(
                  onPressed: c.busy || !c.dirty || c.writeUncertain
                      ? null
                      : c.discard,
                  child: const Text('Discard edits'),
                ),
                OutlinedButton(
                  key: const Key('save-layout'),
                  onPressed: c.busy || !c.dirty || c.writeUncertain
                      ? null
                      : c.save,
                  child: const Text('Save changes'),
                ),
                OutlinedButton(
                  key: const Key('check-layout'),
                  onPressed: c.busy || c.dirty || c.writeUncertain
                      ? null
                      : c.validate,
                  child: const Text('Check layout'),
                ),
                if (c.profile?['layout_export_supported'] == true)
                  OutlinedButton(
                    key: const Key('export-native-layout'),
                    onPressed: c.canExportLayout ? c.exportLayout : null,
                    child: Text(
                      c.profile?['layout_export_label'] ??
                          'Export device layout',
                    ),
                  ),
                FilledButton(
                  key: const Key('apply-layout'),
                  onPressed: c.canApply ? c.apply : null,
                  child: const Text('Apply layout'),
                ),
              ],
            ),
            if (c.exportedLayout != null) ...[
              const SizedBox(height: 12),
              const Text(
                'Exported layout archive (temporary file; copy it to retain):',
              ),
              SelectableText(
                c.exportedLayout!,
                key: const Key('exported-layout-path'),
              ),
            ],
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Apply the checked setup to the idle station'),
              value: c.confirmed,
              onChanged:
                  c.profile?['activation_supported'] == false ||
                      c.busy ||
                      c.dirty ||
                      !c.valid ||
                      c.writeUncertain
                  ? null
                  : (value) => c.confirm(value ?? false),
            ),
            if (c.pendingRequest != null) ...[
              SelectableText('Application request: ${c.pendingRequest}'),
              OutlinedButton(
                onPressed: c.busy ? null : c.inspectPending,
                child: const Text('Inspect application status'),
              ),
            ],
          ] else
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Text(
                definitionError ??
                    (c.draft == null
                        ? 'No setup is open. Startup settings are not assumed to be a saved layout.'
                        : 'This installed driver does not provide a graphical layout definition.'),
              ),
            ),
        ],
      ),
    );
  }

  Widget inspector(BuildContext context, LayoutDefinition definition) {
    final c = widget.controller;
    final position = c.selectedPosition;
    if (position == null)
      return const Text(
        'Select a position on the deck to inspect or place labware.',
      );
    if (lastPosition != position || lastDefinitionId != definition.id) {
      model = null;
      childModel = null;
      childSite = null;
      lastPosition = position;
      lastDefinitionId = definition.id;
    }
    final occupied = definition.occupant(c.proposal!, position);
    final enabled = !c.busy && !c.writeUncertain && c.pendingRequest == null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          '${definition.variant['position_label'] ?? 'Position'} $position',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 16),
        if (occupied != null) ...[
          Text(occupied.name, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(definition.modelLabel(occupied.model)),
          const SizedBox(height: 12),
          Text('Deck > ${occupied.name}'),
          ...definition
              .items(c.proposal!)
              .where((i) => i.parent == occupied.name)
              .map(
                (i) => Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Site ${i.position ?? '—'} · ${i.name} · ${definition.modelLabel(i.model)}',
                  ),
                ),
              ),
          const SizedBox(height: 16),
          if (occupied.collection.editable && occupied.parent == null)
            DropdownButtonFormField<String>(
              key: ValueKey('move-${occupied.id}-${occupied.position}'),
              initialValue: occupied.position,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Move to position'),
              items: definition
                  .destinations(c.proposal!, occupied)
                  .map(
                    (p) => DropdownMenuItem(value: p.id, child: Text(p.label)),
                  )
                  .toList(),
              onChanged: !enabled
                  ? null
                  : (value) {
                      if (value != null) c.move(occupied, value);
                    },
            )
          else
            const Text(
              'Installed module placement is read-only in this editor.',
            ),
          if (occupied.collection.editable)
            Material(
              color: Colors.transparent,
              child: ExpansionTile(
                key: ValueKey('placement-actions-${occupied.id}'),
                title: const Text('Edit placement'),
                children: [
                  placementActions(definition, occupied, enabled),
                  ...definition
                      .items(c.proposal!)
                      .where((i) => i.parent == occupied.name)
                      .map(
                        (item) => Padding(
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(item.name),
                              placementActions(definition, item, enabled),
                            ],
                          ),
                        ),
                      ),
                ],
              ),
            ),
          if (definition.sites(occupied).isNotEmpty)
            siteEditor(context, definition, occupied, enabled),
        ] else ...[
          const Text('Empty position'),
          const SizedBox(height: 16),
          ...definition.collections
              .where(
                (collection) =>
                    collection.editable &&
                    collection.keyed &&
                    definition.positions.any(
                      (p) =>
                          p.id == position &&
                          p.accepts.contains(collection.category),
                    ),
              )
              .map((collection) {
                final options = definition
                    .catalogue(collection, c.proposal!)
                    .where(
                      (o) => definition.fits(
                        c.proposal!,
                        o['id'],
                        position,
                        collection.category,
                      ),
                    )
                    .toList();
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    DropdownButtonFormField<String>(
                      key: ValueKey('catalogue-$position'),
                      initialValue: model,
                      isExpanded: true,
                      decoration: InputDecoration(
                        labelText: collection.category == 'carrier'
                            ? 'Choose carrier'
                            : 'Choose labware',
                      ),
                      items: options
                          .map(
                            (o) => DropdownMenuItem<String>(
                              value: o['id'],
                              child: Text(
                                o['label'],
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          )
                          .toList(),
                      onChanged: !enabled
                          ? null
                          : (value) => setState(() {
                              model = value;
                            }),
                    ),
                    const SizedBox(height: 12),
                    Semantics(
                      label: 'Labware name',
                      container: true,
                      explicitChildNodes: true,
                      child: TextField(
                        key: const Key('labware-name'),
                        controller: name,
                        enabled: enabled,
                        decoration: const InputDecoration(
                          labelText: 'Labware name',
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    FilledButton(
                      key: const Key('add-labware'),
                      onPressed: !enabled || model == null
                          ? null
                          : () {
                              c.add(
                                collection,
                                name.text.trim(),
                                model!,
                                position,
                              );
                              model = null;
                            },
                      child: const Text('Add here'),
                    ),
                  ],
                );
              }),
          if (definition.positions
              .firstWhere((p) => p.id == position)
              .accepts
              .isEmpty)
            const Text('This position is reserved by the driver.'),
        ],
      ],
    );
  }

  Widget siteEditor(
    BuildContext context,
    LayoutDefinition definition,
    LayoutItem parent,
    bool enabled,
  ) {
    final c = widget.controller;
    final collection = definition.collections
        .where((v) => v.parentField != null && v.editable)
        .firstOrNull;
    if (collection == null) return const SizedBox.shrink();
    final children = definition
        .items(c.proposal!)
        .where((i) => i.parent == parent.name)
        .toList();
    final sites = definition
        .sites(parent)
        .where((s) => !children.any((i) => i.position == s))
        .toList();
    final models = definition
        .catalogue(collection, c.proposal!)
        .where((m) => (m['parents'] as List? ?? []).contains(parent.model))
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 24),
        const Divider(),
        const Text(
          'Carrier sites',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 12),
        if (sites.isEmpty)
          const Text('All sites are occupied')
        else if (models.isEmpty)
          const Text(
            'No compatible labware is enabled for native export on this carrier.',
          )
        else ...[
          DropdownButtonFormField<String>(
            key: ValueKey('child-site-${parent.id}-${children.length}'),
            initialValue: sites.contains(childSite) ? childSite : null,
            decoration: const InputDecoration(labelText: 'Empty carrier site'),
            items: sites
                .map((s) => DropdownMenuItem(value: s, child: Text('Site $s')))
                .toList(),
            onChanged: enabled ? (v) => setState(() => childSite = v) : null,
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey('child-model-${parent.id}'),
            initialValue: models.any((m) => m['id'] == childModel)
                ? childModel
                : null,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Compatible labware'),
            items: models
                .map(
                  (m) => DropdownMenuItem<String>(
                    value: m['id'],
                    child: Text(m['label'], overflow: TextOverflow.ellipsis),
                  ),
                )
                .toList(),
            onChanged: enabled ? (v) => setState(() => childModel = v) : null,
          ),
          const SizedBox(height: 12),
          Semantics(
            label: 'Labware name',
            container: true,
            explicitChildNodes: true,
            child: TextField(
              key: const Key('site-labware-name'),
              controller: name,
              enabled: enabled,
              decoration: const InputDecoration(labelText: 'Labware name'),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            key: const Key('place-site-labware'),
            onPressed: !enabled || childSite == null || childModel == null
                ? null
                : () {
                    c.placeChild(
                      collection,
                      name.text.trim(),
                      childModel!,
                      parent,
                      childSite!,
                    );
                    setState(() => childSite = null);
                  },
            child: const Text('Place in site'),
          ),
        ],
      ],
    );
  }

  Widget placementActions(
    LayoutDefinition definition,
    LayoutItem item,
    bool enabled,
  ) {
    final c = widget.controller;
    final models = definition.replacementModels(c.proposal!, item);
    final destinations = item.parent == null
        ? <({LayoutItem parent, String site})>[]
        : definition.childDestinations(c.proposal!, item);
    final removable =
        item.collection.keyed &&
        !definition.items(c.proposal!).any((i) => i.parent == item.name);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DropdownButtonFormField<String>(
          key: ValueKey('replace-${item.id}-${item.model}'),
          initialValue: models.any((m) => m['id'] == item.model)
              ? item.model
              : null,
          isExpanded: true,
          decoration: InputDecoration(labelText: 'Model for ${item.name}'),
          items: models
              .map(
                (m) => DropdownMenuItem<String>(
                  value: m['id'],
                  child: Text(m['label'], overflow: TextOverflow.ellipsis),
                ),
              )
              .toList(),
          onChanged: enabled
              ? (model) {
                  if (model != null) c.replaceModel(item, model);
                }
              : null,
        ),
        if (item.parent != null)
          DropdownButtonFormField<String>(
            key: ValueKey(
              'relocate-${item.id}-${item.parent}-${item.position}',
            ),
            initialValue:
                destinations.any(
                  (d) =>
                      d.parent.name == item.parent && d.site == item.position,
                )
                ? '${item.parent}/${item.position}'
                : null,
            isExpanded: true,
            decoration: InputDecoration(labelText: 'Position for ${item.name}'),
            items: destinations
                .map(
                  (d) => DropdownMenuItem(
                    value: '${d.parent.name}/${d.site}',
                    child: Text('${d.parent.name} · Site ${d.site}'),
                  ),
                )
                .toList(),
            onChanged: enabled
                ? (value) {
                    if (value == null) return;
                    final destination = destinations.firstWhere(
                      (d) => '${d.parent.name}/${d.site}' == value,
                    );
                    c.relocateChild(item, destination.parent, destination.site);
                  }
                : null,
          ),
        TextButton(
          key: ValueKey('remove-${item.id}'),
          onPressed: enabled && removable ? () => c.remove(item) : null,
          child: Text('Remove ${item.name}'),
        ),
        if (!removable && item.collection.keyed)
          const Text('Remove child labware before removing its carrier.'),
      ],
    );
  }
}

class DeckBoard extends StatelessWidget {
  final LayoutDefinition definition;
  final Map<String, dynamic> configuration;
  final String? selected;
  final bool enabled;
  final ValueChanged<String> onSelect;
  const DeckBoard({
    super.key,
    required this.definition,
    required this.configuration,
    required this.selected,
    required this.enabled,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) =>
      definition.variant['presentation'] == 'tracks'
      ? TrackBoard(
          definition: definition,
          configuration: configuration,
          selected: selected,
          enabled: enabled,
          onSelect: onSelect,
        )
      : LayoutBuilder(
          builder: (context, outer) => SizedBox(
            height: max(300, outer.maxWidth / 1.5),
            child: LayoutBuilder(
              builder: (context, bounds) {
                return Stack(
                  children: definition.positions.map((p) {
                    final item = definition.occupant(configuration, p.id);
                    final label = item?.name ?? p.fixedLabel ?? 'Empty';
                    final children = item == null
                        ? <LayoutItem>[]
                        : definition
                              .items(configuration)
                              .where((i) => i.parent == item.name)
                              .toList();
                    return Positioned(
                      left: bounds.maxWidth * p.x / definition.width,
                      top: bounds.maxHeight * p.y / definition.height,
                      width: bounds.maxWidth * p.width / definition.width,
                      height: bounds.maxHeight * p.height / definition.height,
                      child: Padding(
                        padding: const EdgeInsets.all(4),
                        child: Semantics(
                          label: 'Position ${p.label}, $label',
                          selected: selected == p.id,
                          child: OutlinedButton(
                            key: ValueKey('position-${p.id}'),
                            style: OutlinedButton.styleFrom(
                              padding: const EdgeInsets.all(6),
                              backgroundColor: selected == p.id
                                  ? Theme.of(
                                      context,
                                    ).colorScheme.primaryContainer
                                  : Theme.of(context).colorScheme.surface,
                              side: BorderSide(
                                color: selected == p.id
                                    ? Theme.of(context).colorScheme.primary
                                    : Theme.of(
                                        context,
                                      ).colorScheme.outlineVariant,
                              ),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                            onPressed: enabled ? () => onSelect(p.id) : null,
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Text(
                                  p.label,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  label,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  textAlign: TextAlign.center,
                                ),
                                if (children.isNotEmpty)
                                  Text(
                                    children.map((i) => i.name).join(', '),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  }).toList(),
                );
              },
            ),
          ),
        );
}
