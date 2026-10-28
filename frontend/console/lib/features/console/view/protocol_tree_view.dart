import 'package:flutter/material.dart';
import '../interactor/protocol_tree_interactor.dart';
import '../model/protocol_tree.dart';

class NativeProtocolTree extends StatelessWidget {
  final List<dynamic> programs;
  final String? selected;
  final bool busy;
  final void Function(String) inspect, run;
  const NativeProtocolTree({
    super.key,
    required this.programs,
    required this.selected,
    required this.busy,
    required this.inspect,
    required this.run,
  });
  @override
  Widget build(BuildContext context) {
    try {
      return Column(
        children: [
          for (final node in ProtocolTreeInteractor().build(programs))
            entry(node, 0),
        ],
      );
    } on FormatException catch (error) {
      return Text(
        error.message,
        style: const TextStyle(color: Color(0xff924e25)),
      );
    }
  }

  Widget entry(ProtocolTreeNode node, int depth) {
    if (node.directory)
      return ExpansionTile(
        key: PageStorageKey('program-folder:${node.path}'),
        initiallyExpanded: depth == 0,
        leading: const Icon(Icons.folder_outlined),
        title: Text(node.name),
        childrenPadding: const EdgeInsets.only(left: 16),
        children: [for (final child in node.children) entry(child, depth + 1)],
      );
    return Semantics(
      identifier: 'program:${node.path}',
      button: true,
      label: 'Protocol ${node.path}',
      child: GestureDetector(
        onTap: busy ? null : () => inspect(node.path),
        onDoubleTap: busy ? null : () => run(node.path),
        child: ListTile(
          key: ValueKey('program-file:${node.path}'),
          leading: const Icon(Icons.description_outlined),
          selected: selected == node.path,
          title: Text(node.name),
          subtitle: const Text('Select to inspect · double-click to run'),
          trailing: Semantics(
            identifier: 'program.run:${node.path}',
            button: true,
            label: 'Run ${node.path}',
            excludeSemantics: true,
            onTap: busy ? null : () => run(node.path),
            child: IconButton(
              tooltip: 'Run ${node.path}',
              onPressed: busy ? null : () => run(node.path),
              icon: const Icon(Icons.play_arrow),
            ),
          ),
        ),
      ),
    );
  }
}
