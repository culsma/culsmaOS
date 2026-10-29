import 'package:flutter/material.dart';

/// Keep a stable semantic boundary above Navigator and its modal routes.
/// Flutter 3.47.7 can leave orphan AX nodes when hovered overlays are removed
/// during folder/window transitions (flutter/flutter#182444 and #175041).
/// Modal barriers can replace the entire exposed subtree. Keep their children
/// below an explicit boundary so they cannot merge into the engine root.
/// Native accessibility remains enabled by the embedder; do not retain a Dart
/// semantics handle across native bridge reconnections.
class NativeAccessibilityScope extends StatelessWidget {
  final Widget child;
  const NativeAccessibilityScope({super.key, required this.child});
  @override
  Widget build(BuildContext context) => Semantics(
    container: true,
    explicitChildNodes: true,
    child: TooltipVisibility(visible: false, child: child),
  );
}
