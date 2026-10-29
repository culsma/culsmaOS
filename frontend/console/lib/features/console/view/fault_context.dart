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
