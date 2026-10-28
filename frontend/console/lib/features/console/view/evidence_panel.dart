import 'dart:convert';
import 'package:flutter/material.dart';

/// Bounded native presentation; the complete evidence remains in the OS records.
class NativeEvidencePanel extends StatelessWidget {
  final Map<String, dynamic> run;
  const NativeEvidencePanel({super.key, required this.run});
  Widget details(String title, Object? value) {
    final encoded = const JsonEncoder.withIndent('  ').convert(value);
    final truncated = encoded.length > 32000;
    return ExpansionTile(
      title: Text(title),
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (truncated)
                const Text(
                  'Preview limited to 32,000 characters. The complete record is available through the OS API.',
                ),
              Semantics(
                label:
                    '$title details; full structured record is available through the OS API',
                excludeSemantics: true,
                child: SelectableText(
                  truncated ? encoded.substring(0, 32000) : encoded,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final evidence = run['execution_evidence'] as Map? ?? {},
        attempts = evidence['attempts'] as List? ?? [],
        logical = evidence['logical_completions'] as List? ?? [];
    return ExpansionTile(
      title: const Text('Recorded evidence and report'),
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Text(
            run['result']?['headline']?.toString() ??
                'No program report recorded.',
          ),
        ),
        const ListTile(
          title: Text('Device execution attempts'),
          subtitle: Text(
            'OS records; no physical measurements or hardware timing are inferred.',
          ),
        ),
        if (attempts.isEmpty)
          const ListTile(title: Text('No device execution attempts recorded.')),
        for (final attempt in attempts)
          ExpansionTile(
            title: Text('${attempt['step_id'] ?? attempt['effect_id']}'),
            subtitle: Text(
              '${attempt['device_id']} · ${attempt['mode']}\nEvidence: ${attempt['evidence']?['outcome'] ?? attempt['evidence_status'] ?? 'missing'} · Material: ${attempt['registration']?['status'] ?? 'unavailable'}',
            ),
            children: [
              details('Intent and references', {
                'effect_id': attempt['effect_id'],
                'attempt_id': attempt['attempt_id'],
                'context': attempt['context'],
              }),
              details('Execution receipt', attempt['evidence']),
              details('Registration receipt', attempt['registration']),
            ],
          ),
        const ListTile(title: Text('Logical completions · no device action')),
        if (logical.isEmpty)
          const ListTile(title: Text('No logical completions recorded.')),
        for (final item in logical)
          details('${item['step_id'] ?? item['effect_id']}', item),
        const Padding(
          padding: EdgeInsets.all(12),
          child: Text(
            'Missing evidence does not mean an action failed or never happened. Aggregate receipts retain their recorded coverage.',
          ),
        ),
      ],
    );
  }
}
