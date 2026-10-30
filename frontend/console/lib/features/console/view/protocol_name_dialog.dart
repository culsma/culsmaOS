import 'package:flutter/material.dart';

Future<String?> promptProtocolName(
  BuildContext context,
  String title,
  String initial,
) => showDialog<String>(
  context: context,
  builder: (_) => ProtocolNameDialog(title: title, initial: initial),
);

class ProtocolNameDialog extends StatefulWidget {
  final String title, initial;
  const ProtocolNameDialog({
    super.key,
    required this.title,
    required this.initial,
  });
  @override
  State<ProtocolNameDialog> createState() => _ProtocolNameDialogState();
}

class _ProtocolNameDialogState extends State<ProtocolNameDialog> {
  late final TextEditingController name;
  @override
  void initState() {
    super.initState();
    name = TextEditingController(text: widget.initial);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: TextField(
      key: const Key('new-protocol-name'),
      controller: name,
      autofocus: true,
      decoration: const InputDecoration(
        labelText: 'File name',
        helperText: 'Use a .culs file name in Experiments',
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: () => Navigator.pop(context, name.text),
        child: const Text('Save'),
      ),
    ],
  );
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }
}
