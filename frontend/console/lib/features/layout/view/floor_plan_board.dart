import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../console/model/console_model.dart';
import '../model/layout_model.dart';

IconData floorPlanIcon(String kind) => switch (kind) {
  'centrifuge' => Icons.rotate_right,
  'incubator' => Icons.inventory_2_outlined,
  'washer' || 'dispenser' => Icons.water_drop_outlined,
  'shaker' || 'vortexer' => Icons.vibration,
  'temperature' => Icons.thermostat,
  'magnet' => Icons.filter_alt_outlined,
  'pipetting' => Icons.precision_manufacturing_outlined,
  'plate_transport' => Icons.precision_manufacturing_outlined,
  _ => Icons.science_outlined,
};

const floorLevels = {
  'deck': 'Deck level',
  'above': 'Above deck',
  'below': 'Below deck',
};

typedef FloorPlanDrop =
    void Function(String area, String item, Offset position);

class FloorPlanDeck {
  FloorPlanDeck(this.slots, [this.suggestedSize, this.sites = const {}]);
  final List<
    ({String id, String label, String description, Rect rect, int sites})
  >
  slots;
  final Size? suggestedSize;
  final Map<(String, String), Offset> sites;

  bool hasMount(Map<String, dynamic> device) {
    final mount = device['mount'];
    return mount is Map &&
        (mount['kind'] == 'gantry' ||
            (mount['kind'] == 'deck_site' &&
                sites.containsKey((mount['carrier'], mount['site']))));
  }

  factory FloorPlanDeck.fromLayout(Map<String, dynamic>? envelope) {
    final trackDeck = RecordedDeck.fromLayout(envelope);
    final layout = envelope?['layout'];
    final definition = layout?['definition'];
    if (trackDeck != null) {
      final sizes = {
        for (final object in (definition?['objects'] as List? ?? []))
          if (object['dimensions_mm'] case [final num width, final num depth])
            if (width.isFinite && width > 0 && depth.isFinite && depth > 0)
              object['id']: Size(width.toDouble(), depth.toDouble()),
      };
      final depths = trackDeck.carriers.map((c) => sizes[c['id']]?.height);
      final depth = depths.whereType<double>().fold(0.0, math.max);
      final pitches = {
        for (final c in trackDeck.carriers)
          if (sizes[c['id']] case final Size size)
            size.width / (c['span'] as int),
      };
      final count = trackDeck.positions.length;
      return FloorPlanDeck(
        [
          for (final (index, rack) in trackDeck.carriers.indexed)
            (
              id: rack['id'] as String,
              label: RecordedDeck.carrierLabel(index),
              sites: (rack['sites'] as List).length,
              description: [
                rack['model'],
                'Tracks ${rack['start'] + 1}–${rack['start'] + rack['span']}',
                if (sizes[rack['id']] case final Size size)
                  '${size.width.toStringAsFixed(1)} × ${size.height.toStringAsFixed(1)} mm',
                '${(rack['sites'] as List).length} sites',
              ].join(' · '),
              rect: Rect.fromLTWH(
                rack['start'] / count,
                0,
                rack['span'] / count,
                depth > 0 ? (sizes[rack['id']]?.height ?? depth) / depth : 1,
              ),
            ),
        ],
        pitches.length == 1 && depth > 0 && depths.every((v) => v != null)
            ? Size(pitches.single * count, depth)
            : null,
        {
          for (final rack in trackDeck.carriers)
            for (final (index, site) in (rack['sites'] as List).indexed)
              if (site is String)
                (rack['id'] as String, site): Offset(
                  (rack['start'] + rack['span'] / 2) / count,
                  (.125 + .825 * (index + 1.5) / (rack['sites'].length + 1)) *
                      (depth > 0
                          ? (sizes[rack['id']]?.height ?? depth) / depth
                          : 1),
                ),
        },
      );
    }
    if (definition is Map<String, dynamic> &&
        definition['schema'] == 'culsma_layout_v1' &&
        layout?['configuration'] is Map<String, dynamic>) {
      try {
        final slots = LayoutDefinition(definition, layout['configuration']);
        return FloorPlanDeck([
          for (final p in slots.positions)
            (
              id: p.id,
              label: p.label,
              sites: 0,
              description: p.fixedLabel ?? 'Position ${p.label}',
              rect: Rect.fromLTWH(
                p.x / slots.width,
                p.y / slots.height,
                p.width / slots.width,
                p.height / slots.height,
              ),
            ),
        ]);
      } on FormatException {
        return FloorPlanDeck([]);
      }
    }
    return FloorPlanDeck([]);
  }
}

class FloorPlanBoard extends StatelessWidget {
  const FloorPlanBoard({
    super.key,
    required this.plan,
    required this.deck,
    this.level = 'deck',
    this.onArea,
    this.onEquipment,
    this.onRack,
    this.onDrop,
    this.instruments = const [],
    this.onMountedInstrument,
  });

  final Map<String, dynamic> plan;
  final FloorPlanDeck deck;
  final String level;
  final void Function(String area, Offset position)? onArea;
  final ValueChanged<String>? onEquipment, onRack;
  final FloorPlanDrop? onDrop;
  final List<Map<String, dynamic>> instruments;
  final ValueChanged<Map<String, dynamic>>? onMountedInstrument;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final metric = plan['deck'] as Map?;
    final frame = Rect.fromLTWH(
      0,
      0,
      (metric?['width'] as num?)?.toDouble() ??
          deck.suggestedSize?.width ??
          100,
      (metric?['height'] as num?)?.toDouble() ??
          deck.suggestedSize?.height ??
          100,
    );
    final areas = List<Map<String, dynamic>>.from(
      plan['areas'],
    ).where((a) => (a['level'] ?? 'deck') == level);
    final equipment = List<Map<String, dynamic>>.from(plan['equipment']);
    final geometry = {
      for (final area in areas)
        area['id'] as String: Rect.fromLTWH(
          (area['x'] as num).toDouble() *
              (metric == null ? frame.width / 100 : 1),
          (area['y'] as num).toDouble() *
              (metric == null ? frame.height / 100 : 1),
          (area['width'] as num).toDouble() *
              (metric == null ? frame.width / 100 : 1),
          (area['height'] as num).toDouble() *
              (metric == null ? frame.height / 100 : 1),
        ),
    };
    final bounds = geometry.values.fold(frame, (a, b) => a.expandToInclude(b));
    final rackFrame = deck.suggestedSize ?? frame.size;
    final placed = {for (final item in equipment) item['instrument']};
    final mounted = instruments.where(
      (device) =>
          level == 'deck' &&
          !placed.contains(device['id']) &&
          deck.hasMount(device),
    );
    final gantry = mounted.where(
      (device) => device['mount']['kind'] == 'gantry',
    );
    final atSite = <Offset, List<Map<String, dynamic>>>{};
    for (final device in mounted.where(
      (device) => device['mount']['kind'] == 'deck_site',
    )) {
      final mount = device['mount'];
      final point = deck.sites[(mount['carrier'], mount['site'])]!;
      atSite.putIfAbsent(point, () => []).add(device);
    }

    Widget marker(Map<String, dynamic> device, {bool compact = false}) {
      final icon = Icon(floorPlanIcon(device['kind']), size: compact ? 16 : 20);
      final tap = onMountedInstrument;
      final id = ValueKey("mounted-instrument-${device['id']}");
      if (compact) {
        return Tooltip(
          message: device['name'],
          child: Material(
            color: colors.primaryContainer,
            shape: CircleBorder(side: BorderSide(color: colors.primary)),
            child: InkWell(
              key: id,
              customBorder: const CircleBorder(),
              onTap: tap == null ? null : () => tap(device),
              child: Semantics(
                label: device['name'],
                button: tap != null,
                child: SizedBox.square(
                  dimension: 28,
                  child: Center(child: icon),
                ),
              ),
            ),
          ),
        );
      }
      return ActionChip(
        key: id,
        avatar: icon,
        label: Text(device['name']),
        onPressed: tap == null ? null : () => tap(device),
      );
    }

    return LayoutBuilder(
      builder: (context, box) {
        final availableWidth = math.max(1, box.maxWidth - 32);
        final height = (availableWidth * bounds.height / bounds.width + 32)
            .clamp(140.0, 320.0);
        final scale = math.min(
          availableWidth / bounds.width,
          (height - 32) / bounds.height,
        );
        final dx =
            (box.maxWidth - bounds.width * scale) / 2 - bounds.left * scale;
        final dy = (height - bounds.height * scale) / 2 - bounds.top * scale;
        Rect project(Rect rect) => Rect.fromLTWH(
          dx + rect.left * scale,
          dy + rect.top * scale,
          rect.width * scale,
          rect.height * scale,
        );
        Positioned region(Rect rect, Widget child) =>
            Positioned.fromRect(rect: project(rect), child: child);
        final footprints = {
          for (final item in equipment)
            if (geometry[item['area_id']] case final Rect area)
              item['id']: item['width'] == null
                  ? Rect.fromCenter(
                      center: Offset(
                        area.left +
                            (item['x'] as num) *
                                (metric == null ? area.width / 100 : 1),
                        area.top +
                            (item['y'] as num) *
                                (metric == null ? area.height / 100 : 1),
                      ),
                      width: 24 / scale,
                      height: 24 / scale,
                    )
                  : Rect.fromLTWH(
                      area.left + (item['x'] as num),
                      area.top + (item['y'] as num),
                      (item['width'] as num).toDouble(),
                      (item['height'] as num).toDouble(),
                    ),
        };
        final occupied = footprints.values.map(project).toList();
        final labelStyle = Theme.of(context).textTheme.labelMedium!;
        Widget equipmentTile(Map<String, dynamic> item) {
          final tile = Tooltip(
            key: ValueKey("floor-instrument-${item['id']}"),
            message: [
              item['name'],
              if (item['handoff'] != null)
                "${item['handoff']} · route unverified",
            ].join(' · '),
            child: Material(
              color: colors.primaryContainer,
              clipBehavior: Clip.hardEdge,
              shape: RoundedRectangleBorder(
                side: BorderSide(color: colors.primary),
                borderRadius: BorderRadius.circular(5),
              ),
              child: InkWell(
                onTap: onEquipment == null
                    ? null
                    : () => onEquipment!(item['id']),
                child: LayoutBuilder(
                  builder: (context, size) {
                    if (size.maxWidth < 14 || size.maxHeight < 14)
                      return const SizedBox.shrink();
                    final icon = Icon(
                      floorPlanIcon(item['kind']),
                      size: 14,
                      semanticLabel: item['name'],
                    );
                    final lineHeight = _labelSize(
                      context,
                      'A',
                      labelStyle,
                    ).height;
                    if (size.maxWidth < 40 ||
                        size.maxHeight < 24 + lineHeight) {
                      return Center(child: icon);
                    }
                    return Padding(
                      padding: const EdgeInsets.all(4),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          icon,
                          const SizedBox(height: 2),
                          Flexible(
                            child: Text(
                              item['name'],
                              style: labelStyle,
                              maxLines: size.maxHeight >= 24 + 2 * lineHeight
                                  ? 2
                                  : 1,
                              textAlign: TextAlign.center,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ),
            ),
          );
          if (metric == null || onDrop == null) return tile;
          return Draggable<String>(
            data: item['id'],
            dragAnchorStrategy: pointerDragAnchorStrategy,
            feedback: Material(
              child: Chip(
                avatar: Icon(floorPlanIcon(item['kind'])),
                label: Text(item['name']),
              ),
            ),
            child: tile,
          );
        }

        final diagram = SizedBox(
          height: height,
          child: Stack(
            children: [
              if (level == 'deck')
                region(
                  frame,
                  DecoratedBox(
                    decoration: BoxDecoration(
                      color: colors.surfaceContainerHighest,
                      border: Border.all(color: colors.outlineVariant),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: deck.slots.isEmpty
                        ? const Center(child: Text('Deck'))
                        : Stack(
                            children: [
                              for (final slot in deck.slots)
                                Positioned.fromRect(
                                  rect: Rect.fromLTWH(
                                    slot.rect.left * rackFrame.width * scale,
                                    slot.rect.top * rackFrame.height * scale,
                                    slot.rect.width * rackFrame.width * scale,
                                    slot.rect.height * rackFrame.height * scale,
                                  ),
                                  child: Tooltip(
                                    message:
                                        '${slot.label} · ${slot.description}',
                                    child: Material(
                                      color: colors.surface,
                                      clipBehavior: Clip.hardEdge,
                                      shape: RoundedRectangleBorder(
                                        side: BorderSide(
                                          color: colors.outlineVariant,
                                        ),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: InkWell(
                                        onTap: onRack == null
                                            ? null
                                            : () => onRack!(slot.id),
                                        child: Stack(
                                          children: [
                                            Align(
                                              alignment: slot.sites == 0
                                                  ? Alignment.center
                                                  : Alignment.topCenter,
                                              child: LayoutBuilder(
                                                builder: (context, constraints) {
                                                  final size = _labelSize(
                                                    context,
                                                    slot.label,
                                                    labelStyle,
                                                  );
                                                  if (size.width + 2 >
                                                          constraints
                                                              .maxWidth ||
                                                      size.height >
                                                          constraints
                                                              .maxHeight) {
                                                    return const SizedBox.shrink();
                                                  }
                                                  return Text(
                                                    slot.label,
                                                    style: labelStyle,
                                                    maxLines: 1,
                                                  );
                                                },
                                              ),
                                            ),
                                            for (
                                              var i = 1;
                                              i <= slot.sites;
                                              i++
                                            )
                                              Align(
                                                alignment: Alignment(
                                                  0,
                                                  -.75 +
                                                      1.65 *
                                                          i /
                                                          (slot.sites + 1),
                                                ),
                                                child: FractionallySizedBox(
                                                  widthFactor: .7,
                                                  child: ColoredBox(
                                                    color:
                                                        colors.outlineVariant,
                                                    child: const SizedBox(
                                                      height: 1,
                                                    ),
                                                  ),
                                                ),
                                              ),
                                          ],
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                  ),
                ),
              for (final area in areas)
                region(
                  geometry[area['id']]!,
                  DragTarget<String>(
                    key: ValueKey("floor-area-${area['id']}"),
                    onWillAcceptWithDetails: (_) => onDrop != null,
                    onAcceptWithDetails: (details) {
                      final rect = geometry[area['id']]!;
                      final renderBox = context.findRenderObject() as RenderBox;
                      final point = renderBox.globalToLocal(details.offset);
                      onDrop!(
                        area['id'],
                        details.data,
                        Offset(
                          (point.dx - dx) / scale - rect.left,
                          (point.dy - dy) / scale - rect.top,
                        ),
                      );
                    },
                    builder: (context, candidates, _) {
                      Offset? pointer;
                      final tap = onArea;
                      return Tooltip(
                        message: area['name'],
                        child: Material(
                          color: candidates.isEmpty
                              ? colors.surfaceContainerLow
                              : colors.primaryContainer,
                          shape: RoundedRectangleBorder(
                            side: BorderSide(color: colors.outlineVariant),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: InkWell(
                            onTapDown: tap == null
                                ? null
                                : (details) =>
                                      pointer = details.localPosition / scale,
                            onTapCancel: tap == null
                                ? null
                                : () => pointer = null,
                            onTap: tap == null
                                ? null
                                : () {
                                    final position = pointer ?? Offset.zero;
                                    pointer = null;
                                    tap(area['id'], position);
                                  },
                          ),
                        ),
                      );
                    },
                  ),
                ),
              for (final item in equipment)
                if (footprints[item['id']] case final Rect rect)
                  region(rect, equipmentTile(item)),
              for (final entry in atSite.entries)
                Positioned(
                  left:
                      (project(frame).left +
                              entry.key.dx * rackFrame.width * scale -
                              (30 * entry.value.length - 2) / 2)
                          .clamp(
                            0.0,
                            math.max(
                              0.0,
                              box.maxWidth - 30 * entry.value.length,
                            ),
                          ),
                  top:
                      (project(frame).top +
                              entry.key.dy * rackFrame.height * scale -
                              14)
                          .clamp(0.0, height - 28),
                  child: Row(
                    spacing: 2,
                    children: [
                      for (final device in entry.value)
                        marker(device, compact: true),
                    ],
                  ),
                ),
              for (final area in areas)
                if (_captionRect(
                      context,
                      area['name'],
                      labelStyle,
                      project(geometry[area['id']]!),
                      occupied,
                    )
                    case final Rect caption)
                  Positioned.fromRect(
                    rect: caption,
                    child: IgnorePointer(
                      child: ExcludeSemantics(
                        child: Text(
                          area['name'],
                          style: labelStyle,
                          maxLines: 2,
                        ),
                      ),
                    ),
                  ),
            ],
          ),
        );
        if (gantry.isEmpty) return diagram;
        final deckRect = project(frame);
        final railWidth = math.min(
          box.maxWidth,
          math.max(150.0, deckRect.width),
        );
        final railLeft = (deckRect.center.dx - railWidth / 2).clamp(
          0.0,
          box.maxWidth - railWidth,
        );
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.only(left: railLeft),
              child: SizedBox(
                width: railWidth,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    Positioned(
                      left: 0,
                      right: 0,
                      child: Divider(
                        thickness: 4,
                        color: colors.outlineVariant,
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Wrap(
                        alignment: WrapAlignment.center,
                        spacing: 8,
                        children: [for (final device in gantry) marker(device)],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            diagram,
          ],
        );
      },
    );
  }

  static Size _labelSize(BuildContext context, String label, TextStyle style) {
    final painter = TextPainter(
      text: TextSpan(text: label, style: style),
      textDirection: Directionality.of(context),
      textScaler: MediaQuery.textScalerOf(context),
      maxLines: 1,
    )..layout();
    final size = painter.size;
    painter.dispose();
    return size;
  }

  static Rect? _captionRect(
    BuildContext context,
    String label,
    TextStyle style,
    Rect area,
    List<Rect> occupied,
  ) {
    final inside = area.deflate(4);
    if (inside.isEmpty) return null;
    final painter = TextPainter(
      text: TextSpan(text: label, style: style),
      textDirection: Directionality.of(context),
      textScaler: MediaQuery.textScalerOf(context),
      maxLines: 2,
    )..layout(maxWidth: inside.width);
    final size = painter.size;
    final fits = !painter.didExceedMaxLines && size.height <= inside.height;
    painter.dispose();
    if (!fits) return null;
    for (final corner in [
      inside.topLeft,
      Offset(inside.right - size.width, inside.top),
      Offset(inside.left, inside.bottom - size.height),
      Offset(inside.right - size.width, inside.bottom - size.height),
    ]) {
      final rect = corner & size;
      if (occupied.every((footprint) => !footprint.inflate(2).overlaps(rect))) {
        return rect;
      }
    }
    return null;
  }
}
