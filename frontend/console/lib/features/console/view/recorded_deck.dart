import 'dart:math';
import 'package:flutter/material.dart';
import '../model/console_model.dart';

/// Shared rendering of declared driver geometry; every track has the same pitch.
class RecordedDeckBoard extends StatelessWidget {
  final RecordedDeck deck;
  final String? selectedEntity;
  final Map<String, GlobalKey> keys;
  final void Function(Map<String, dynamic>)? onItem;
  final void Function(String, String)? onSite;
  const RecordedDeckBoard({
    super.key,
    required this.deck,
    required this.keys,
    this.selectedEntity,
    this.onItem,
    this.onSite,
  });
  @override
  Widget build(BuildContext context) {
    final maxSites = deck.carriers.fold<int>(
      1,
      (value, c) => max(value, (c['sites'] as List).length),
    );
    final maxStack = deck.carriers.fold<int>(
      1,
      (value, c) => max(value, (c['placements'] as List).length),
    );
    final rowHeight = max(80.0, min(140.0, 30.0 + maxStack * 12));
    final height = maxSites * rowHeight + 60;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          deck.label,
          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 12),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: SizedBox(
            width: deck.positions.length * 32,
            height: height,
            child: Stack(
              children: [
                for (var i = 0; i < deck.positions.length; i++)
                  Positioned(
                    left: i * 32,
                    top: 0,
                    bottom: 0,
                    width: 32,
                    child: Container(
                      decoration: const BoxDecoration(
                        color: Color(0xffedf3f8),
                        border: Border(
                          right: BorderSide(color: Color(0xffccd9e4)),
                        ),
                      ),
                      alignment: Alignment.bottomCenter,
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        '${deck.positions[i]['label'] ?? deck.positions[i]['id']}',
                        style: const TextStyle(fontSize: 10),
                      ),
                    ),
                  ),
                for (var i = 0; i < deck.carriers.length; i++)
                  carrier(deck.carriers[i], i, rowHeight, maxSites),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget carrier(
    Map<String, dynamic> carrier,
    int index,
    double rowHeight,
    int maxSites,
  ) {
    final sites = carrier['sites'] as List,
        placements = carrier['placements'] as List;
    return Positioned(
      left: carrier['start'] * 32.0 + 2,
      top: 8,
      width: carrier['span'] * 32.0 - 4,
      height: maxSites * rowHeight + 10,
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xffdce7f0),
          border: Border.all(color: const Color(0xff91a8bd)),
          borderRadius: BorderRadius.circular(4),
        ),
        padding: const EdgeInsets.all(3),
        child: Column(
          children: [
            Text(
              'C${index + 1}',
              style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
            ),
            for (final site in sites)
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Column(
                    children: [
                      if (carrier['span'] >= 3)
                        Text('$site', style: const TextStyle(fontSize: 10)),
                      for (final placed in placements.where(
                        (p) => p['site'] == site,
                      ))
                        Expanded(
                          child: Semantics(
                            button: onItem != null,
                            identifier: 'layout:${placed['id']}',
                            label: 'Configured item ${placed['id']}',
                            child: InkWell(
                              onTap: onItem == null
                                  ? null
                                  : () => onItem!(
                                      Map<String, dynamic>.from(placed),
                                    ),
                              child: Container(
                                key: keys.putIfAbsent(
                                  placed['id'],
                                  () => GlobalKey(),
                                ),
                                width: double.infinity,
                                margin: const EdgeInsets.symmetric(vertical: 1),
                                decoration: BoxDecoration(
                                  color: placed['id'] == selectedEntity
                                      ? const Color(0xffbddbf0)
                                      : Colors.white,
                                  border: Border.all(
                                    color: placed['id'] == selectedEntity
                                        ? const Color(0xff247a92)
                                        : const Color(0xffb7cadb),
                                  ),
                                  borderRadius: BorderRadius.circular(3),
                                ),
                                alignment: Alignment.center,
                                padding: const EdgeInsets.all(3),
                                child: Tooltip(
                                  message: placed['id'],
                                  child: Text(
                                    carrier['span'] < 3
                                        ? '$site'
                                        : placed['id'],
                                    textAlign: TextAlign.center,
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(fontSize: 10),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      if (!placements.any((p) => p['site'] == site))
                        Expanded(
                          child: Semantics(
                            key: ValueKey('layout-site:${carrier['id']}/$site'),
                            identifier: 'layout-site:${carrier['id']}/$site',
                            label: 'Empty position ${carrier['id']} site $site',
                            button: onSite != null,
                            child: InkWell(
                              onTap: onSite == null
                                  ? null
                                  : () =>
                                        onSite!(carrier['id'], site.toString()),
                              child: Container(
                                width: double.infinity,
                                alignment: Alignment.center,
                                decoration: BoxDecoration(
                                  border: Border.all(
                                    color: const Color(0xffb7cadb),
                                  ),
                                  borderRadius: BorderRadius.circular(3),
                                ),
                                child: const Icon(
                                  Icons.add,
                                  size: 18,
                                  color: Color(0xff758b9e),
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
