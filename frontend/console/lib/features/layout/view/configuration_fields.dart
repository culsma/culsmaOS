import 'package:flutter/material.dart';
import '../interactor/layout_controller.dart';
import '../model/layout_model.dart';

/// Driver-defined choices only; changing a model never silently resets a setup.
class ConfigurationFields extends StatelessWidget {
  final LayoutController controller;
  const ConfigurationFields({super.key, required this.controller});
  @override
  Widget build(BuildContext context) {
    final c = controller;
    final fields = (c.profile?['fields'] as List? ?? [])
        .cast<Map<String, dynamic>>()
        .where(
          (f) =>
              ['platform', 'instruments'].contains(f['section']) &&
              f['options'] is List,
        )
        .toList();
    if (fields.isEmpty || c.proposal == null) return const SizedBox.shrink();
    final enabled = !c.busy && !c.writeUncertain && c.pendingRequest == null;
    return Semantics(
      button: true,
      label: 'Device configuration',
      child: Card(
        elevation: 0,
        color: Colors.white,
        child: ExpansionTile(
          title: const Text('Device configuration'),
          subtitle: Text(
            fields
                .map(
                  (f) =>
                      '${f['label']}: ${LayoutData.at(c.proposal!, f['path']) ?? 'Unset'}',
                )
                .join(' · '),
            maxLines: 2,
          ),
          childrenPadding: const EdgeInsets.all(16),
          children: fields.map((field) {
            final options = (field['options'] as List).cast<String>();
            final value = LayoutData.at(c.proposal!, field['path']);
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: DropdownButtonFormField<String>(
                key: ValueKey('field-${field['path'].join('-')}-$value'),
                initialValue: options.contains(value) ? value : null,
                isExpanded: true,
                decoration: InputDecoration(labelText: field['label']),
                items: options
                    .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                    .toList(),
                onChanged: enabled
                    ? (v) {
                        if (v == null) return;
                        final updated = LayoutData.copy(c.proposal!);
                        final path = List<String>.from(field['path']);
                        final parent =
                            LayoutData.at(
                                  updated,
                                  path.take(path.length - 1).toList(),
                                )
                                as Map<String, dynamic>;
                        parent[path.last] = v;
                        c.edit(updated);
                      }
                    : null,
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}
