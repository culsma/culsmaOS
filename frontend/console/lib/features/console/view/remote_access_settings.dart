import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../api/console_api.dart';
import '../interactor/remote_access_interactor.dart';

class RemoteAccessSettings extends StatefulWidget {
  final RemoteAccessInteractor controller;
  const RemoteAccessSettings({super.key, required this.controller});

  @override
  State<RemoteAccessSettings> createState() => _RemoteAccessSettingsState();
}

class _RemoteAccessSettingsState extends State<RemoteAccessSettings> {
  Map<String, dynamic>? status;
  bool busy = false;
  String? error;

  @override
  void initState() {
    super.initState();
    update('status');
  }

  Future<void> update(
    String action, [
    Map<String, dynamic> fields = const {},
  ]) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final reply = await widget.controller.execute(action, fields);
      final token = reply.remove('token') as String?;
      if (!mounted) return;
      setState(() => status = reply);
      if (token != null) await showCredential(token);
    } on ConsoleApiError catch (failure) {
      if (!mounted) return;
      setState(
        () => error = switch (failure.code) {
          'REMOTE_PORT_UNAVAILABLE' =>
            'The MCP port is in use. Close the other gateway and try again.',
          _ => 'Remote access settings could not be updated. (${failure.code})',
        },
      );
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> pair() async {
    String name = '';
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Pair a device'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'A paired device can edit files and control runs while remote access is on.',
            ),
            const SizedBox(height: 16),
            TextField(
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Device name',
                hintText: 'e.g. Yang-Mac',
              ),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9_.@-]')),
                LengthLimitingTextInputFormatter(128),
              ],
              onChanged: (value) => name = value,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (name.isNotEmpty) Navigator.pop(context, true);
            },
            child: const Text('Pair'),
          ),
        ],
      ),
    );
    if (mounted && accepted == true) await update('pair', {'name': name});
  }

  Future<void> showCredential(String token) => showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (context) => AlertDialog(
      title: const Text('Device credential'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Save this credential in the paired device’s MCP client. It is shown once.',
          ),
          const SizedBox(height: 12),
          SelectableText(token),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: token));
            if (context.mounted) Navigator.pop(context);
          },
          child: const Text('Copy and close'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final current = status;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Remote access', style: Theme.of(context).textTheme.titleMedium),
        if (current != null) ...[
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Allow remote MCP connections'),
            subtitle: Text(
              'Station port ${current['port']}. Connect through a private tunnel.',
            ),
            value: current['enabled'] == true,
            onChanged: busy ? null : (on) => update(on ? 'enable' : 'disable'),
          ),
          for (final device in current['pairings'] as List)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.devices),
              title: Text(device['name'] as String),
              trailing: TextButton(
                onPressed: busy
                    ? null
                    : () => update('unpair', {'id': device['id']}),
                child: const Text('Revoke'),
              ),
            ),
          OutlinedButton.icon(
            onPressed: busy ? null : pair,
            icon: const Icon(Icons.link),
            label: const Text('Pair a device'),
          ),
        ],
        if (busy) const LinearProgressIndicator(),
        if (error != null) ...[
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          TextButton(
            onPressed: busy ? null : () => update('status'),
            child: const Text('Refresh'),
          ),
        ],
        const Divider(height: 32),
      ],
    );
  }
}
