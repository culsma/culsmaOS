import 'package:flutter/material.dart';

import '../interactor/layout_controller.dart';
import 'floor_plan_board.dart';

class InstrumentSettingsDialog extends StatefulWidget {
  const InstrumentSettingsDialog({
    super.key,
    required this.controller,
    required this.instrument,
    required this.fingerprint,
    required this.canEdit,
    this.editPlacement,
  });

  final LayoutController controller;
  final Map<String, dynamic> instrument;
  final String? fingerprint;
  final bool Function() canEdit;
  final VoidCallback? editPlacement;

  @override
  State<InstrumentSettingsDialog> createState() =>
      _InstrumentSettingsDialogState();
}

class _InstrumentSettingsDialogState extends State<InstrumentSettingsDialog> {
  final form = GlobalKey<FormState>();
  final values = <String, num>{};
  bool changed = false, attempted = false;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      final item = widget.instrument;
      final fields = List<Map<String, dynamic>>.from(item['fields'] ?? []);
      final details = Map<String, dynamic>.from(item['details'] ?? {});
      final pending = attempted && c.pendingRequest != null;
      final editable = widget.fingerprint != null && widget.canEdit();
      return PopScope(
        canPop: !c.busy,
        child: AlertDialog(
          scrollable: true,
          icon: Icon(floorPlanIcon(item['kind'])),
          title: Text(item['name']),
          content: SizedBox(
            width: 420,
            child: Form(
              key: form,
              onChanged: () => setState(() => changed = true),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 18,
                children: [
                  if (c.busy && attempted) const LinearProgressIndicator(),
                  if (item['note'] case final String note) Text(note),
                  for (final entry in details.entries)
                    Text('${entry.key} · ${entry.value}'),
                  if (item['id'] == null)
                    const Text(
                      'This device is listed in the workstation layout. Its operating controls are unavailable in this workstation.',
                    )
                  else if (fields.isEmpty && item['note'] == null)
                    const Text(
                      'The driver exposes no editable workstation settings for this device.',
                    ),
                  for (final field in fields)
                    TextFormField(
                      key: ValueKey<String>(field['id']),
                      initialValue: field['value'].toString(),
                      decoration: InputDecoration(
                        labelText: '${field['label']} (${field['unit']})',
                        border: const OutlineInputBorder(),
                      ),
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                        signed: true,
                      ),
                      enabled: editable && c.canChangeInstrument,
                      validator: (text) {
                        final number = num.tryParse(text?.trim() ?? '');
                        final num? min = field['min'], max = field['max'];
                        if (number == null || !number.isFinite) {
                          return 'Enter a number.';
                        }
                        if (min != null &&
                            max != null &&
                            (number < min || number > max)) {
                          return 'Enter a value from $min to $max.';
                        }
                        if (min != null && number < min) {
                          return 'Enter a value of at least $min.';
                        }
                        return null;
                      },
                      onSaved: (text) {
                        final number = num.parse(text!.trim());
                        if (number != field['value']) {
                          values[field['id']] = number;
                        }
                      },
                    ),
                  if (fields.isNotEmpty && !editable)
                    const Text(
                      'Save or discard other layout edits before applying settings.',
                    ),
                  if (attempted && c.message != null)
                    Semantics(liveRegion: true, child: Text(c.message!)),
                ],
              ),
            ),
          ),
          actions: [
            if (widget.editPlacement != null)
              TextButton(
                onPressed: c.busy || pending
                    ? null
                    : () => Navigator.pop(context, 'placement'),
                child: const Text('Edit placement'),
              ),
            TextButton(
              onPressed: c.busy ? null : () => Navigator.pop(context),
              child: Text(fields.isEmpty ? 'Close' : 'Cancel'),
            ),
            if (pending)
              FilledButton(
                onPressed: c.busy
                    ? null
                    : () async {
                        final applied = await c.inspectPending();
                        if (applied && context.mounted) {
                          Navigator.pop(context, 'applied');
                        }
                      },
                child: const Text('Check apply status'),
              )
            else if (fields.isNotEmpty)
              FilledButton(
                onPressed: changed && editable && c.canChangeInstrument
                    ? apply
                    : null,
                child: const Text('Apply settings'),
              ),
          ],
        ),
      );
    },
  );

  Future<void> apply() async {
    if (!form.currentState!.validate()) return;
    values.clear();
    form.currentState!.save();
    if (values.isEmpty) {
      setState(() => changed = false);
      return;
    }
    setState(() => attempted = true);
    final applied = await widget.controller.applyInstrument(
      widget.instrument['id'],
      widget.fingerprint!,
      values,
    );
    if (applied && mounted) Navigator.pop(context, 'applied');
  }
}
