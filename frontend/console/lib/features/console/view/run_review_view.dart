import 'package:flutter/material.dart';
import '../interactor/console_interactor.dart';

/// Review before admission; final execution preflight remains owned by the OS.
class NativeRunReviewView extends StatelessWidget {
  final NativeConsoleInteractor console;
  const NativeRunReviewView({super.key, required this.console});
  @override
  Widget build(BuildContext context) {
    final c = console;
    final preparation = c.inspection?['preparation'];
    final requirements = preparation?['requirements'] as List? ?? [];
    final checked = c.launchReview != null;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            c.working
                ? 'Checking the experiment…'
                : checked
                ? 'Ready to confirm'
                : 'Check needs attention',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 12),
          Text(c.selectedFile ?? ''),
          const SizedBox(height: 16),
          if (c.working) const LinearProgressIndicator(),
          if (checked) ...[
            const Text('Protocol checked. No experiment has started.'),
            if (preparation?['status'] == 'available')
              const Text(
                'The requested containers can be mapped to the current layout.',
              )
            else
              const Text('This backend does not provide a loading preview.'),
            const SizedBox(height: 12),
            const Text(
              'Stock and device readiness are checked before dispatch. This preview does not detect physical loading or reserve supplies.',
            ),
            if (requirements.isNotEmpty) ...[
              const SizedBox(height: 20),
              Text(
                'Initial loading requirements',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              for (final item in requirements)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(
                    item['name']?.toString() ?? item['container_id'].toString(),
                  ),
                  trailing: Text("${item['initial_volume_uL']} µL"),
                ),
            ],
            const SizedBox(height: 24),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                FilledButton.icon(
                  key: const Key('confirm-run'),
                  onPressed: c.working || c.dirty ? null : c.confirmLaunch,
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Confirm run'),
                ),
                TextButton(
                  onPressed: c.working ? null : () => c.closeWindow(c.active!),
                  child: const Text('Cancel'),
                ),
              ],
            ),
          ] else if (!c.working) ...[
            Text(c.message ?? 'Open the protocol again to repeat the checks.'),
            if (c.messageDetails != null)
              ExpansionTile(
                title: const Text('Technical details'),
                children: [SelectableText(c.messageDetails!)],
              ),
          ],
        ],
      ),
    );
  }
}
