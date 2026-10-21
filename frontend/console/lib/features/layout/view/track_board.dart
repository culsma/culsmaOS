import 'dart:math';
import 'package:flutter/material.dart';
import '../model/layout_model.dart';

class TrackBoard extends StatelessWidget {
  final LayoutDefinition definition;
  final Map<String, dynamic> configuration;
  final String? selected;
  final bool enabled;
  final ValueChanged<String> onSelect;
  const TrackBoard({
    super.key,
    required this.definition,
    required this.configuration,
    required this.selected,
    required this.enabled,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    const pitch = 30.0;
    final width = definition.width * pitch;
    final carriers = definition
        .items(configuration)
        .where((i) => i.parent == null)
        .toList();
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: const Color(0xffdce3ec)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SizedBox(
          width: width,
          height: 370,
          child: Stack(
            children: [
              ...definition.positions.map(
                (p) => Positioned(
                  left: p.x * pitch,
                  top: 0,
                  width: p.width * pitch,
                  bottom: 0,
                  child: Semantics(
                    label:
                        'Track ${p.label}, ${definition.occupant(configuration, p.id)?.name ?? 'Empty'}',
                    button: true,
                    selected: selected == p.id,
                    child: InkWell(
                      key: ValueKey('position-${p.id}'),
                      onTap: enabled ? () => onSelect(p.id) : null,
                      child: Container(
                        decoration: BoxDecoration(
                          border: const Border(
                            right: BorderSide(color: Color(0xffe5ebf0)),
                          ),
                          color: selected == p.id
                              ? const Color(0xffe4eef8)
                              : null,
                        ),
                        child: Column(
                          children: [
                            const SizedBox(height: 12),
                            Text(p.label, style: const TextStyle(fontSize: 10)),
                            const Spacer(),
                            Text(p.label, style: const TextStyle(fontSize: 10)),
                            const SizedBox(height: 12),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              ...carriers.map((item) {
                final covered = definition.positions
                    .where((p) => definition.footprint(item).contains(p.id))
                    .toList();
                if (covered.isEmpty) return const SizedBox.shrink();
                final left = covered.map((p) => p.x).reduce(min);
                final right = covered.map((p) => p.x + p.width).reduce(max);
                final sites = definition.sites(item);
                final narrow = covered.length < 4;
                final children = definition
                    .items(configuration)
                    .where((i) => i.parent == item.name)
                    .toList();
                final isSelected = definition
                    .footprint(item)
                    .contains(selected);
                return Positioned(
                  left: left * pitch + 4,
                  width: (right - left) * pitch - 8,
                  top: 42,
                  bottom: 42,
                  child: Semantics(
                    label:
                        'Carrier ${item.name}, tracks ${covered.first.label} to ${covered.last.label}',
                    selected: isSelected,
                    child: OutlinedButton(
                      key: ValueKey('carrier-${item.name}'),
                      onPressed: enabled
                          ? () => onSelect(item.position!)
                          : null,
                      style: OutlinedButton.styleFrom(
                        padding: EdgeInsets.all(narrow ? 1 : 8),
                        backgroundColor: isSelected
                            ? const Color(0xffe4eef8)
                            : const Color(0xfff2f5f8),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                      child: Column(
                        children: [
                          Text(
                            item.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: 6),
                          ...sites.map((site) {
                            final child = children
                                .where((i) => i.position == site)
                                .firstOrNull;
                            return Expanded(
                              child: Container(
                                margin: const EdgeInsets.symmetric(vertical: 3),
                                padding: EdgeInsets.all(narrow ? 1 : 5),
                                width: double.infinity,
                                decoration: BoxDecoration(
                                  color: child == null
                                      ? Colors.white
                                      : const Color(0xffd3e8e2),
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text(
                                  '$site  ${child?.name ?? 'Empty site'}',
                                  style: const TextStyle(fontSize: 11),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            );
                          }),
                        ],
                      ),
                    ),
                  ),
                );
              }),
            ],
          ),
        ),
      ),
    );
  }
}
