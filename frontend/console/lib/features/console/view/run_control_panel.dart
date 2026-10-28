import 'package:flutter/material.dart';
import '../interactor/run_control_interactor.dart';

class NativeRunControlPanel extends StatelessWidget {
  final NativeRunControlInteractor controller;
  final Map<String, dynamic> run;
  const NativeRunControlPanel({
    super.key,
    required this.controller,
    required this.run,
  });
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final c = controller,
          id = run['run_id'] as String,
          actions = c.actions(run),
          receipt = c.receipts[id];
      if (actions.isEmpty &&
          c.pending[id] == null &&
          receipt == null &&
          c.errors[id] == null &&
          (run['pending_controls'] as List? ?? []).isEmpty &&
          run['status'] != 'needs_reconciliation')
        return const SizedBox.shrink();
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Run controls',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              const Text(
                'Pause applies at an execution boundary. Cancel stops further work and preserves completed actions.',
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  for (final action in actions)
                    OutlinedButton.icon(
                      onPressed: () => c.command(run, action),
                      icon: Icon(
                        action == 'pause'
                            ? Icons.pause
                            : action == 'resume'
                            ? Icons.play_arrow
                            : Icons.stop,
                      ),
                      label: Text(
                        '${action[0].toUpperCase()}${action.substring(1)} run',
                      ),
                    ),
                ],
              ),
              if (c.pending[id] != null) ...[
                Text(
                  '${c.pending[id]!['action']} request retained; waiting for a matching worker receipt.',
                ),
                Wrap(
                  spacing: 12,
                  children: [
                    TextButton(
                      onPressed: c.busy.contains(id) ? null : () => c.check(id),
                      child: const Text('Check control status'),
                    ),
                    if (c.receipts[id]?['status'] != 'pending')
                      TextButton(
                        onPressed: c.busy.contains(id)
                            ? null
                            : () => c.retry(id),
                        child: const Text('Retry same control request'),
                      ),
                  ],
                ),
              ],
              if (receipt != null)
                Text(
                  '${receipt['action']}: ${receipt['status']}${receipt['error'] == null ? '' : ' · ${receipt['error']}'}',
                ),
              if (c.errors[id] != null)
                Text(
                  c.errors[id]!,
                  style: const TextStyle(color: Color(0xff924e25)),
                ),
              for (final row in run['pending_controls'] as List? ?? [])
                Text(
                  '${row['action']} · ${row['status'] ?? 'pending'} · ${row['request_id']}',
                ),
              if (run['status'] == 'needs_reconciliation')
                const Text(
                  'Execution needs reconciliation. Isolation is retained; this console cannot restart or reconcile the experiment.',
                ),
            ],
          ),
        ),
      );
    },
  );
}
