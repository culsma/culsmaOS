import 'package:flutter/material.dart';
import '../interactor/setup_interactor.dart';
import '../interactor/run_review_interactor.dart';
import 'preparation_layout.dart';

class NativeSetupPanel extends StatelessWidget {
  final NativeSetupInteractor controller;
  final Map<String, dynamic> run;
  const NativeSetupPanel({
    super.key,
    required this.controller,
    required this.run,
  });
  @override
  Widget build(BuildContext context) {
    final c = controller, id = run['run_id'] as String, plan = c.plans[id];
    if (plan == null)
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Reading the experiment loading plan…'),
          if (c.errors[id] != null) Text(c.errors[id]!),
          TextButton(
            onPressed: c.busy ? null : () => c.observe(run),
            child: const Text('Refresh loading plan'),
          ),
        ],
      );
    final editable = run['status'] == 'awaiting_setup',
        valid = plan['fingerprint'] is String;
    final history = plan['activity'] as List? ?? [];
    final latestError =
        history.isNotEmpty && history.first['status'] == 'failed'
        ? history.first['error']?.toString()
        : null;
    final problem = c.errors[id] ?? latestError;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 16),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              editable
                  ? 'Prepare loading · awaiting execution confirmation'
                  : 'Experiment loading plan',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              '${editable ? 'Plan' : 'Preparation status'}: ${plan['phase'] ?? 'unavailable'}',
            ),
            if (editable)
              const Text(
                'Not submitted for execution. Confirm loading to submit and run.',
              ),
            if (!editable)
              const Text(
                'Loading confirmation records preparation only; it does not mean execution succeeded.',
              ),
            const Text(
              'These are declared loading requirements. The system cannot detect physical loading.',
            ),
            if (problem != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  'Placement change could not be applied. The previous plan is retained.\n$problem',
                  style: const TextStyle(color: Color(0xff924e25)),
                ),
              ),
            if (!valid)
              Text(
                plan['error']?.toString() ??
                    'Waiting for a valid loading plan.',
              ),
            if (c.statuses[id] != null) Text(c.statuses[id]!),
            NativePreparationLayout(
              key: ValueKey('setup-layout-$id'),
              plan: plan,
              review: NativeRunReviewInteractor(),
            ),
            if (editable && valid) preferences(context, id, plan),
            if (c.pending[id] != null) ...[
              const SizedBox(height: 16),
              const Text(
                'A loading request is unresolved. Its identity is retained; it is not automatically repeated.',
              ),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  OutlinedButton(
                    onPressed: c.busy ? null : () => c.check(id),
                    child: const Text('Check request status'),
                  ),
                  TextButton(
                    onPressed: c.busy ? null : () => c.retry(id),
                    child: const Text('Retry same request'),
                  ),
                ],
              ),
            ] else if (editable && valid && plan['phase'] == 'planned')
              FilledButton(
                onPressed:
                    c.busy ||
                        c.repository == null ||
                        c.edits[id]?['dirty'] == true
                    ? null
                    : () => c.command(id, 'begin'),
                child: const Text('Start loading'),
              )
            else if (editable && valid && plan['phase'] == 'loading') ...[
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: c.acknowledged(id),
                onChanged: c.busy || c.edits[id]?['dirty'] == true
                    ? null
                    : (v) => c.acknowledge(id, v ?? false),
                title: const Text('I loaded every item according to this plan'),
              ),
              FilledButton(
                onPressed:
                    c.busy ||
                        c.repository == null ||
                        c.edits[id]?['dirty'] == true ||
                        !c.acknowledged(id)
                    ? null
                    : () => c.command(id, 'confirm'),
                child: const Text('Confirm loading and run'),
              ),
            ],
            if (plan['confirmation'] != null)
              Text(
                'Confirmation: ${plan['confirmation']['source']} · physical detection: no',
              ),
            ExpansionTile(
              title: const Text('Preparation history'),
              children: [
                for (final entry in plan['activity'] as List? ?? [])
                  ListTile(
                    title: Text('${entry['action']} · ${entry['status']}'),
                    subtitle: Text(
                      '${entry['origin']} · ${entry['request_id']}',
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget preferences(
    BuildContext context,
    String id,
    Map<String, dynamic> plan,
  ) {
    final c = controller,
        current = c.edit(id),
        stale = current['fingerprint'] != plan['fingerprint'];
    final enabled = !c.busy && c.pending[id] == null && !stale;
    return ExpansionTile(
      title: const Text('Placement preferences'),
      maintainState: true,
      children: [
        if (stale) ...[
          const Text(
            'The shared plan changed. Reload current preferences before editing.',
          ),
          TextButton(
            onPressed: c.busy ? null : () => c.reloadPreferences(id),
            child: const Text('Reload current preferences'),
          ),
        ] else ...[
          for (final item in plan['items'] as List? ?? [])
            placement(context, id, item, plan, enabled),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                OutlinedButton(
                  onPressed: enabled && current['dirty'] == true
                      ? () => c.command(id, 'revise')
                      : null,
                  child: const Text('Apply placement requirements'),
                ),
                TextButton(
                  onPressed: enabled && current['dirty'] == true
                      ? () => c.reloadPreferences(id)
                      : null,
                  child: const Text('Discard placement edits'),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget placement(
    BuildContext context,
    String id,
    Map item,
    Map plan,
    bool enabled,
  ) {
    final c = controller,
        allocation = item['allocation_id'] as String,
        values = c.edit(id)['values'];
    final mode = values['fixed']?[allocation] != null
        ? 'fixed'
        : values['preferred']?[allocation] != null
        ? 'preferred'
        : 'automatic';
    final address = Map<String, dynamic>.from(
      values[mode]?[allocation] ?? item['address'],
    );
    final candidates = (plan['candidates'] as List? ?? [])
        .where(
          (p) =>
              (p['kinds'] as List).contains(item['kind']) &&
              (p['capacity_uL'] as num) >= (item['capacity_uL'] as num) &&
              (item['carrier'] == null || p['well'] == item['well']),
        )
        .toList();
    final labware = candidates.map((p) => p['labware'] as String).toSet();
    final wells = candidates
        .where((p) => p['labware'] == address['labware'])
        .map((p) => p['well'] as String)
        .toSet();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(item['name'] ?? allocation),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey('setup-mode-$id-$allocation-$mode'),
            initialValue: mode,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Placement mode'),
            items: [
              'automatic',
              'fixed',
              'preferred',
            ].map((v) => DropdownMenuItem(value: v, child: Text(v))).toList(),
            onChanged: enabled
                ? (v) {
                    if (v != null) c.setPreference(id, allocation, v, address);
                  }
                : null,
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey(
              'setup-labware-$id-$allocation-${address['labware']}',
            ),
            initialValue: labware.contains(address['labware'])
                ? address['labware']
                : null,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Labware'),
            items: labware
                .map(
                  (v) => DropdownMenuItem(
                    value: v,
                    child: Text(v, overflow: TextOverflow.ellipsis),
                  ),
                )
                .toList(),
            onChanged: enabled && mode != 'automatic'
                ? (v) {
                    if (v != null) {
                      final options = candidates
                          .where((p) => p['labware'] == v)
                          .toList();
                      c.setPreference(id, allocation, mode, {
                        'labware': v,
                        'well': options.first['well'],
                      });
                    }
                  }
                : null,
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey(
              'setup-well-$id-$allocation-${address['well']}-${address['labware']}',
            ),
            initialValue: wells.contains(address['well'])
                ? address['well']
                : null,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Position'),
            items: wells
                .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                .toList(),
            onChanged: enabled && mode != 'automatic'
                ? (v) {
                    if (v != null)
                      c.setPreference(id, allocation, mode, {
                        'labware': address['labware'],
                        'well': v,
                      });
                  }
                : null,
          ),
        ],
      ),
    );
  }
}
