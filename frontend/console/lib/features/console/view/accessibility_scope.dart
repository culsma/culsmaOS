import 'package:flutter/material.dart';

/// Keep control semantics while avoiding tooltip overlay traversal grafting.
/// Flutter 3.47.7 can leave orphan AX nodes when hovered overlays are removed
/// during folder/window transitions (flutter/flutter#182444 and #175041).
/// Do not disable ensureSemantics or the native accessibility bridge.
class NativeAccessibilityScope extends StatelessWidget {
  final Widget child;
  const NativeAccessibilityScope({super.key, required this.child});
  @override
  Widget build(BuildContext context) =>
      TooltipVisibility(visible: false, child: child);
}
