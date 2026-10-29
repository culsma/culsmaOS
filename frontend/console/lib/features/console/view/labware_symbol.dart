import 'package:flutter/material.dart';

/// Generic UI symbols. The driver supplies the kind; model codes are never parsed.
class NativeLabwareSymbol extends StatelessWidget {
  final String kind;
  final double size;
  const NativeLabwareSymbol({super.key, required this.kind, this.size = 24});
  @override
  Widget build(BuildContext context) => Icon(
    switch (kind) {
      'plate' => Icons.grid_on,
      'tips' => Icons.apps,
      'reservoir' => Icons.water_drop_outlined,
      'tube' => Icons.science_outlined,
      _ => Icons.inventory_2_outlined,
    },
    size: size,
    semanticLabel: switch (kind) {
      'plate' => 'Plate',
      'tips' => 'Tip rack',
      'reservoir' => 'Reagent vessel',
      'tube' => 'Tube',
      _ => 'Container',
    },
  );
}
