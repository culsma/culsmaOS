import 'package:flutter/material.dart';
import '../model/run_progress.dart';

class NativeRunProgressPanel extends StatelessWidget {
  final Map run;
  const NativeRunProgressPanel({super.key, required this.run});
  @override
  Widget build(BuildContext context) {
    final progress = NativeRunProgress.fromRun(run);
    if (progress == null) return const SizedBox.shrink();
    return Semantics(
      container: true,
      label: 'Experiment progress',
      child: Card(
        key: const Key('run-progress'),
        margin: const EdgeInsets.symmetric(vertical: 16),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                progress.title,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 12),
              const LinearProgressIndicator(
                semanticsLabel: 'Experiment is being processed',
              ),
              const SizedBox(height: 12),
              Text(progress.message),
            ],
          ),
        ),
      ),
    );
  }
}
