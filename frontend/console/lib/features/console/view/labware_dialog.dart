import 'package:flutter/material.dart';
import '../interactor/labware_interactor.dart';
import '../interactor/console_interactor.dart';
import 'supply_panel.dart';

class NativeLabwareDialog extends StatelessWidget {
  final NativeLabwareInteractor controller;
  final VoidCallback? replaceTips;
  const NativeLabwareDialog({
    super.key,
    required this.controller,
    this.replaceTips,
  });
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final c = controller, t = c.target;
      if (!c.editing) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (context.mounted && Navigator.of(context).canPop())
            Navigator.of(context).pop();
        });
      }
      final enabled = !c.busy && c.pending == null && !c.stale && c.ready;
      return AlertDialog(
        title: Text(c.editingCarrier ? 'Replace rack' : 'Edit rack position'),
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t?['label'] ??
                      c.selection?['item'] ??
                      '${c.selection?['parent'] ?? ''} · ${c.selection?['site'] ?? ''}',
                ),
                const SizedBox(height: 16),
                if (c.busy) const LinearProgressIndicator(),
                if (c.error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(
                      c.error!,
                      style: const TextStyle(color: Color(0xff924e25)),
                    ),
                  ),
                if (c.pending != null) ...[
                  const Text(
                    'Saving the layout. Waiting for the station to confirm the change.',
                  ),
                  TextButton(
                    onPressed: c.busy ? null : c.checkStatus,
                    child: const Text('Check save status'),
                  ),
                ] else if (t != null) ...[
                  Text(
                    'Current contents: ${(t['occupants'] as List).join(', ').isEmpty ? 'Empty' : (t['occupants'] as List).join(', ')}',
                  ),
                  if (replaceTips != null)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      child: OutlinedButton(
                        onPressed: c.busy || c.changed ? null : replaceTips,
                        child: const Text('Replace tip box…'),
                      ),
                    ),
                  if (t['current_model'] != null)
                    Text('Current model: ${t['current_model']}'),
                  if (c.editingCarrier)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        'This changes the declared rack configuration. Physically install the matching rack before loading an experiment.',
                      ),
                    ),
                  if (t['note'] != null) Text(t['note']),
                  if (t['reason'] != null)
                    Text(t['reason'])
                  else ...[
                    const SizedBox(height: 20),
                    DropdownButtonFormField<String>(
                      key: ValueKey('labware-category-${c.category}'),
                      initialValue: c.category.isEmpty ? null : c.category,
                      decoration: const InputDecoration(labelText: 'Contents'),
                      isExpanded: true,
                      items: [
                        if (!c.editingCarrier)
                          const DropdownMenuItem(
                            value: 'empty',
                            child: Text('Empty position'),
                          ),
                        ...c.models
                            .map((m) => m['category'] as String)
                            .toSet()
                            .map(
                              (v) => DropdownMenuItem(
                                value: v,
                                child: Text(
                                  {
                                        'plate': 'Plate',
                                        'reservoir': 'Reservoir',
                                        'tips': 'Tip rack',
                                        'carrier': 'Rack',
                                      }[v] ??
                                      v,
                                ),
                              ),
                            ),
                      ],
                      onChanged: enabled
                          ? (v) {
                              if (v != null) c.chooseCategory(v);
                            }
                          : null,
                    ),
                    if (c.category.isNotEmpty && c.category != 'empty') ...[
                      const SizedBox(height: 20),
                      DropdownButtonFormField<String>(
                        key: ValueKey('labware-model-${c.category}-${c.model}'),
                        initialValue: c.model.isEmpty ? null : c.model,
                        decoration: const InputDecoration(
                          labelText: 'Labware model',
                        ),
                        isExpanded: true,
                        items: c.models
                            .where((m) => m['category'] == c.category)
                            .map(
                              (m) => DropdownMenuItem<String>(
                                value: m['id'],
                                child: Text(
                                  m['label'],
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            )
                            .toList(),
                        onChanged: enabled
                            ? (v) {
                                if (v != null) c.chooseModel(v);
                              }
                            : null,
                      ),
                      if ((t['occupants'] as List).isEmpty) ...[
                        const SizedBox(height: 12),
                        Text(
                          'New identifier: ${c.name}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ],
                    if (!c.editingCarrier &&
                        (t['occupants'] as List).isNotEmpty &&
                        c.changed)
                      const Padding(
                        padding: EdgeInsets.only(top: 16),
                        child: Text(
                          'This also clears linked program bindings and liquid or tip settings. Review them before the next experiment.',
                        ),
                      ),
                  ],
                ],
                if (c.stale && t != null)
                  const Padding(
                    padding: EdgeInsets.only(top: 12),
                    child: Text(
                      'The layout changed. Close and reopen this position.',
                    ),
                  ),
              ],
            ),
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
        actions: [
          TextButton(
            onPressed: c.busy
                ? null
                : () {
                    c.close();
                  },
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: c.canSave ? c.save : null,
            child: Text(
              c.busy || c.pending != null ? 'Saving…' : 'Save changes',
            ),
          ),
        ],
      );
    },
  );
}

Future<void> showLabwareEditor(
  BuildContext context,
  NativeConsoleInteractor console,
  Map<String, dynamic> desired,
) async {
  if (console.labware.editing) return;
  final loading = console.labware.edit(
    desired,
    settingsBlocked:
        console.layout.dirty ||
        console.layout.busy ||
        console.layout.writeUncertain ||
        console.layout.pendingRequest != null,
  );
  await showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => NativeLabwareDialog(
      controller: console.labware,
      replaceTips:
          desired['item'] == console.supplies.data?['resource_id'] &&
              console.supplies.supported
          ? () => showTipReplacement(context, console)
          : null,
    ),
  );
  await loading;
  console.labware.close();
  await console.refresh();
}
