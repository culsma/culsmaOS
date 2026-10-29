import 'dart:convert';
import 'package:flutter/material.dart';
import '../interactor/developer_interactor.dart';
import 'fault_context.dart';

class NativeDeveloperView extends StatelessWidget {
  final NativeDeveloperInteractor controller;
  const NativeDeveloperView({super.key, required this.controller});
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final c = controller;
      final result = c.result;
      final guidance = result?['guidance'] as Map? ?? {};
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(
            'Exception tests',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 12),
          const Text(
            'Developer diagnostics · isolated local model',
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          const Text(
            'These buttons inject test conditions into private model state. They do not operate instruments, change the workstation inventory or complete any physical loading.',
          ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              for (final entry in const {
                'tip_unavailable': 'Tips unavailable',
                'liquid_insufficient': 'Insufficient liquid',
                'interrupted': 'Execution interrupted',
              }.entries)
                OutlinedButton.icon(
                  key: ValueKey('fault-test-${entry.key}'),
                  onPressed: c.busy ? null : () => c.trigger(entry.key),
                  icon: const Icon(Icons.bug_report_outlined),
                  label: Text(entry.value),
                ),
              if (result != null)
                TextButton(
                  onPressed: c.busy ? null : c.clear,
                  child: const Text('Clear test result'),
                ),
            ],
          ),
          if (c.busy)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: LinearProgressIndicator(),
            ),
          if (c.error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Text(
                c.error!,
                style: const TextStyle(color: Colors.brown),
              ),
            ),
          if (result?['supported'] == false)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                result?['message'] ??
                    'These tests are unavailable for this driver.',
              ),
            ),
          if (result?['supported'] == true) ...[
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'INJECTED TEST RESULT',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      guidance['title'] ?? 'Test finished',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 8),
                    Text(guidance['message'] ?? ''),
                    const SizedBox(height: 12),
                    if (guidance['context'] == null)
                      Text(
                        result!['outcome'] == 'rejected'
                            ? 'Handling: rejected before execution.'
                            : 'Handling: outcome unknown; automatic replay and resume are blocked.',
                      ),
                    const SizedBox(height: 12),
                    NativeFaultContext(guidance: guidance),
                    const Text(
                      'Operator guidance',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    for (final entry
                        in (guidance['next_steps'] as List? ?? [])
                            .asMap()
                            .entries)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text('${entry.key + 1}. ${entry.value}'),
                      ),
                    const SizedBox(height: 12),
                    const Text(
                      'The isolation described above belongs to this diagnostic test. Your live workstation is unchanged. Acknowledging a message cannot replace tips, add liquid or resume an instrument.',
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Processing flow',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            for (final entry in (result!['flow'] as List).asMap().entries)
              ListTile(
                leading: CircleAvatar(
                  radius: 14,
                  child: Text('${entry.key + 1}'),
                ),
                title: Text(entry.value),
              ),
            ExpansionTile(
              title: const Text('Technical details'),
              children: [
                SelectableText(
                  const JsonEncoder.withIndent('  ').convert(result),
                ),
              ],
            ),
          ],
        ],
      );
    },
  );
}
