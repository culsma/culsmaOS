import 'package:flutter/material.dart';

/// Present backend-owned fault facts consistently in experiments and diagnostics.
class NativeFaultContext extends StatelessWidget {
  final Map guidance;
  const NativeFaultContext({super.key, required this.guidance});
  @override
  Widget build(BuildContext context) {
    final facts = guidance['context'];
    if (facts is! Map) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final detail in (guidance['fault_details'] as List? ?? []))
            if (detail is Map)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        detail['title']?.toString() ?? 'Device diagnostic',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      if (detail['operation'] != null)
                        Text('Affected operation: ${detail['operation']}'),
                      Text(
                        'Information source: ${detail['basis_label'] ?? 'Not reported'}',
                      ),
                      for (final fact
                          in (detail['facts'] as Map? ?? {}).entries)
                        Text('${fact.key}: ${fact.value}'),
                      Text(detail['check']?.toString() ?? ''),
                    ],
                  ),
                ),
              ),
          for (final entry in const {
            'execution': 'Execution status',
            'device_stop': 'Device stop status',
            'operation': 'Affected operation',
            'location': 'Affected location',
            'recovery': 'Recovery availability',
          }.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text.rich(
                TextSpan(
                  children: [
                    TextSpan(
                      text: '${entry.value}: ',
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    TextSpan(
                      text: facts[entry.key]?.toString() ?? 'Not reported.',
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
