import 'package:flutter/material.dart';
import '../interactor/console_interactor.dart';
import '../interactor/supply_interactor.dart';

Future<void> showTipReplacement(
  BuildContext context,
  NativeConsoleInteractor console,
) async {
  final c = console.supplies;
  if (c.editing ||
      console.layout.dirty ||
      console.layout.busy ||
      console.layout.writeUncertain ||
      console.layout.pendingRequest != null)
    return;
  await c.refresh();
  if (!context.mounted) return;
  c.open();
  await showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => NativeSupplyDialog(controller: c),
  );
  c.close();
  await console.refresh();
}

class NativeSupplyPanel extends StatelessWidget {
  final NativeConsoleInteractor console;
  const NativeSupplyPanel({super.key, required this.console});
  @override
  Widget build(BuildContext context) {
    final c = console.supplies, d = c.data;
    if (d == null)
      return c.error == null ? const SizedBox.shrink() : Text(c.error!);
    if (!c.supported)
      return ExpansionTile(
        title: const Text('Consumables'),
        children: [
          Text(d['reason'] ?? 'Replacement is not supported by this backend.'),
        ],
      );
    final stock = d['stock'],
        available = (stock['available'] as List).length,
        used = (stock['used'] as List).length;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Tips · $available available · $used used in current box',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            Text(
              '${d['resource_id']} · local simulation · load ${stock['load_id']}',
            ),
            const Text(
              'Declared model inventory; no physical loading is detected.',
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: c.busy || console.layout.dirty
                  ? null
                  : () => showTipReplacement(context, console),
              icon: const Icon(Icons.inventory_2_outlined),
              label: const Text('Replace tip box…'),
            ),
            if (c.message != null) Text(c.message!),
            if (c.error != null)
              Text(c.error!, style: const TextStyle(color: Color(0xff924e25))),
            if (c.pending != null)
              TextButton(
                onPressed: c.busy ? null : () => c.check(),
                child: const Text('Check retained replacement request'),
              ),
            for (final request in d['pending'] as List? ?? [])
              TextButton(
                onPressed: c.busy ? null : () => c.check(request['request_id']),
                child: const Text('Resolve pending station replacement'),
              ),
            ExpansionTile(
              title: const Text('Tip-box loading history'),
              children: [
                for (final record in d['history'] as List? ?? [])
                  ListTile(
                    title: Text(
                      '${record['status']} · ${(record['positions'] as List).length} declared positions',
                    ),
                    subtitle: Text(
                      '${record['request_id']} · prior lifetime consumption ${record['baseline']}',
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class NativeSupplyDialog extends StatelessWidget {
  final NativeSupplyInteractor controller;
  const NativeSupplyDialog({super.key, required this.controller});
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final c = controller;
      if (!c.editing)
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (context.mounted && Navigator.of(context).canPop())
            Navigator.of(context).pop();
        });
      return AlertDialog(
        title: const Text('Replace simulated tip box'),
        content: SizedBox(
          width: 540,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Source: ${c.data?['resource_id'] ?? 'Unavailable'}'),
                const SizedBox(height: 12),
                const Text(
                  'Register a new box at this tip source. The previous box and its consumption remain in the loading history. Liquid quantities and prior runs are unchanged.',
                ),
                if (c.busy) const LinearProgressIndicator(),
                if (c.error != null) ...[
                  const Text(
                    'The tip-box update needs attention. Review the supply status below before trying again.',
                    style: TextStyle(color: Color(0xff924e25)),
                  ),
                  ExpansionTile(
                    title: const Text('Technical details'),
                    children: [SelectableText(c.error!)],
                  ),
                ],
                if (c.supported && c.data?['stock']?['ready'] != true)
                  const Text(
                    'Tip stock is not verified. Review the workstation and resolve outstanding operations before registering another box.',
                  ),
                if (!c.supported)
                  Text(c.data?['reason'] ?? 'This backend is unsupported.')
                else if (c.pending != null ||
                    (c.data?['pending'] as List? ?? []).isNotEmpty) ...[
                  const Text(
                    'Replacement is unresolved. Do not declare another box until its receipt is reconciled.',
                  ),
                  TextButton(
                    onPressed: c.busy
                        ? null
                        : () => c.check(
                            c.pending?['request_id'] ??
                                c.data!['pending'][0]['request_id'],
                          ),
                    child: const Text('Check replacement status'),
                  ),
                ] else ...[
                  const SizedBox(height: 16),
                  const Text('Positions containing new simulated tips'),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: c.positions
                        .map(
                          (p) => FilterChip(
                            label: Text(p),
                            selected: c.selected.contains(p),
                            onSelected: c.busy ? null : (v) => c.choose(p, v),
                          ),
                        )
                        .toList(),
                  ),
                  const SizedBox(height: 12),
                  Text('${c.selected.length} positions selected'),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    value: c.acknowledged,
                    onChanged: c.busy ? null : (v) => c.acknowledge(v ?? false),
                    title: const Text(
                      'Declare a new simulated box with these available positions',
                    ),
                  ),
                  if (c.stale)
                    const Text(
                      'Supply state changed. Close and reopen before replacing the box.',
                    ),
                ],
              ],
            ),
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
        actions: [
          TextButton(
            onPressed: c.busy ? null : c.close,
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: c.canApply ? c.apply : null,
            child: Text(c.busy ? 'Registering…' : 'Register new box'),
          ),
        ],
      );
    },
  );
}
