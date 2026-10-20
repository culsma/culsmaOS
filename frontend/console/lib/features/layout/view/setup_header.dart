import 'package:flutter/material.dart';
import '../interactor/layout_controller.dart';

class SetupHeader extends StatelessWidget {
  final LayoutController controller;
  const SetupHeader({super.key, required this.controller});
  @override
  Widget build(BuildContext context) {
    final c = controller;
    final blocked =
        c.busy || c.dirty || c.writeUncertain || c.pendingRequest != null;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Color(0xffdce3ec))),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  c.profile?['label'] ?? 'Station workspace',
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  c.profile?['activation_supported'] == false
                      ? 'Offline proposal · active station unchanged'
                      : 'Local station · ${c.active?['host']?['status'] ?? 'Connecting'}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xff64768a),
                  ),
                ),
              ],
            ),
          ),
          Semantics(
            button: true,
            label: 'Open station setup',
            child: PopupMenuButton<String>(
              tooltip: blocked
                  ? 'Save or discard changes before opening another setup'
                  : 'Open station setup',
              enabled: !blocked,
              child: const Padding(
                padding: EdgeInsets.all(8),
                child: Row(
                  children: [
                    Icon(Icons.folder_open_outlined, size: 20),
                    SizedBox(width: 8),
                    Text('Open setup'),
                  ],
                ),
              ),
              onSelected: (id) {
                if (id.startsWith('new:')) {
                  c.createSetup(
                    c.profiles.firstWhere(
                      (p) => p['driver'] == id.substring(4),
                    ),
                  );
                } else {
                  c.openDraft(id);
                }
              },
              itemBuilder: (_) => [
                ...c.drafts.map(
                  (d) => PopupMenuItem<String>(
                    value: d['draft_id'],
                    child: Text('Open: ${d['title']}'),
                  ),
                ),
                if (c.drafts.isNotEmpty) const PopupMenuDivider(),
                ...c.profiles
                    .where((p) => p['layout'] != null)
                    .map(
                      (p) => PopupMenuItem<String>(
                        value: 'new:${p['driver']}',
                        child: Text('New: ${p['label']}'),
                      ),
                    ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
