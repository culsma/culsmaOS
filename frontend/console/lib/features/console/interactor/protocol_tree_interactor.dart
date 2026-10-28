import '../model/protocol_tree.dart';

/// Presentation-only hierarchy of program IDs returned by the OS.
class ProtocolTreeInteractor {
  List<ProtocolTreeNode> build(List<dynamic> programs) {
    final root = <ProtocolTreeNode>[];
    for (final program in programs) {
      final id = program['program_id'];
      if (id is! String ||
          id.isEmpty ||
          id.contains('\\') ||
          id.split('/').any((p) => p.isEmpty || p == '.' || p == '..'))
        throw const FormatException('Invalid program path in the OS listing.');
      final parts = id.split('/');
      var children = root;
      var parent = '';
      for (var i = 0; i < parts.length; i++) {
        final part = parts[i], path = parent.isEmpty ? part : '$parent/$part';
        var node = children.where((n) => n.name == part).firstOrNull;
        if (i == parts.length - 1) {
          if (node != null)
            throw const FormatException(
              'Conflicting program paths in the OS listing.',
            );
          children.add(
            ProtocolTreeNode(
              part,
              path,
              program: Map<String, dynamic>.from(program),
            ),
          );
        } else {
          if (node != null && !node.directory)
            throw const FormatException(
              'Conflicting program paths in the OS listing.',
            );
          if (node == null) {
            node = ProtocolTreeNode(part, path, children: []);
            children.add(node);
          }
          children = node.children;
          parent = path;
        }
      }
    }
    return sort(root);
  }

  List<ProtocolTreeNode> sort(List<ProtocolTreeNode> nodes) {
    nodes.sort((a, b) {
      if (a.directory != b.directory) return a.directory ? -1 : 1;
      final order = a.name.toLowerCase().compareTo(b.name.toLowerCase());
      return order == 0 ? a.name.compareTo(b.name) : order;
    });
    for (final node in nodes) if (node.directory) sort(node.children);
    return nodes;
  }
}
