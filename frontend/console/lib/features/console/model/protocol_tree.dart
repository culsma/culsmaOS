class ProtocolTreeNode {
  final String name, path;
  final Map<String, dynamic>? program;
  final List<ProtocolTreeNode> children;
  const ProtocolTreeNode(
    this.name,
    this.path, {
    this.program,
    this.children = const [],
  });
  bool get directory => program == null;
}
