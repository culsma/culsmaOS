import 'package:flutter/material.dart';
import '../../layout/interactor/layout_controller.dart';

/// Uses the same saved-selection and activation endpoints as MCP.
class ExecutionSettings extends StatefulWidget {
  final LayoutController controller;
  final bool blocked;
  final Future<void> Function()? onApplied;
  const ExecutionSettings({
    super.key,
    required this.controller,
    this.blocked = false,
    this.onApplied,
  });

  @override
  State<ExecutionSettings> createState() => ExecutionSettingsState();
}

class ExecutionSettingsState extends State<ExecutionSettings> {
  Object? identity;
  Future<Map<String, dynamic>>? options;
  int? selected;

  void reload() {
    identity = null;
    setState(() {});
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      final currentIdentity = (c.draft?['draft_id'], c.draft?['revision']);
      if (c.canSelectExecution && identity != currentIdentity) {
        identity = currentIdentity;
        selected = null;
        options = c.executionOptions();
      }
      final enabled = c.canSelectExecution && !widget.blocked;
      return Padding(
        padding: const EdgeInsets.only(bottom: 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Execution mode',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            if (c.draft == null)
              const Text('Open a saved setup to choose its execution mode.')
            else if (c.dirty)
              const Text(
                'Save or discard setup edits before changing execution mode.',
              )
            else
              FutureBuilder<Map<String, dynamic>>(
                future: options,
                builder: (context, snapshot) {
                  if (snapshot.hasError) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Execution options unavailable: ${snapshot.error}',
                        ),
                        TextButton(
                          onPressed: enabled ? reload : null,
                          child: const Text('Reload execution options'),
                        ),
                      ],
                    );
                  }
                  if (snapshot.connectionState != ConnectionState.done ||
                      !snapshot.hasData) {
                    return const Text('Reading execution options…');
                  }
                  final choices = List<Map<String, dynamic>>.from(
                    snapshot.data!['implementations'],
                  );
                  final saved = snapshot.data!['selected'];
                  final savedIndex = choices.indexWhere(
                    (v) =>
                        v['mode'] == saved['mode'] &&
                        v['simulator'] == saved['simulator'],
                  );
                  final value =
                      selected ?? (savedIndex < 0 ? null : savedIndex);
                  final changed = value != savedIndex;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Saved setup: ${c.draft!['title']} · r${c.draft!['revision']}',
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<int>(
                        key: ValueKey(
                          'execution-choice-${c.draft!['draft_id']}-${c.draft!['revision']}',
                        ),
                        initialValue: value,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Execution implementation',
                        ),
                        items: [
                          for (var i = 0; i < choices.length; i++)
                            DropdownMenuItem(
                              value: i,
                              child: Text(
                                choices[i]['label'],
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                        ],
                        onChanged: enabled
                            ? (v) => setState(() => selected = v)
                            : null,
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        children: [
                          OutlinedButton(
                            onPressed: enabled && value != null && changed
                                ? () => c.selectExecution({
                                    'mode': choices[value]['mode'],
                                    'simulator': choices[value]['simulator'],
                                  })
                                : null,
                            child: const Text('Save execution choice'),
                          ),
                          OutlinedButton(
                            onPressed: enabled && !changed ? c.validate : null,
                            child: const Text('Check saved setup'),
                          ),
                        ],
                      ),
                      if (c.valid && !changed) ...[
                        CheckboxListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text(
                            'Apply this saved setup and execution mode',
                          ),
                          value: c.confirmed,
                          onChanged: enabled
                              ? (v) => c.confirm(v ?? false)
                              : null,
                        ),
                        FilledButton(
                          onPressed: enabled && c.canApply
                              ? () async {
                                  await c.apply();
                                  await widget.onApplied?.call();
                                }
                              : null,
                          child: const Text('Apply saved setup'),
                        ),
                      ],
                      if (c.pendingRequest != null)
                        TextButton(
                          onPressed: c.busy
                              ? null
                              : () async {
                                  await c.inspectPending();
                                  await widget.onApplied?.call();
                                },
                          child: const Text('Check pending application'),
                        ),
                      const SizedBox(height: 8),
                      const Text(
                        'Saving does not switch the active station. Apply while idle; this does not start an experiment.',
                      ),
                      if (c.message != null) Text(c.message!),
                    ],
                  );
                },
              ),
          ],
        ),
      );
    },
  );
}
