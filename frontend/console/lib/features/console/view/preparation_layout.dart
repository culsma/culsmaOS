import 'package:flutter/material.dart';
import '../interactor/run_review_interactor.dart';
import '../model/console_model.dart';
import 'recorded_deck.dart';
import 'labware_symbol.dart';

/// One persistent deck view: annotations and cards refer to the same loading items.
class NativePreparationLayout extends StatefulWidget {
  final Map plan;
  final NativeRunReviewInteractor review;
  const NativePreparationLayout({
    super.key,
    required this.plan,
    required this.review,
  });
  @override
  State<NativePreparationLayout> createState() =>
      NativePreparationLayoutState();
}

class NativePreparationLayoutState extends State<NativePreparationLayout> {
  final scroll = ScrollController();
  final itemKeys = <String, GlobalKey>{};
  String? selected;
  void select(String id, {bool reveal = false}) {
    setState(() => selected = id);
    if (reveal && itemKeys[id]?.currentContext != null)
      Scrollable.ensureVisible(
        itemKeys[id]!.currentContext!,
        alignment: .5,
        duration: const Duration(milliseconds: 200),
      );
  }

  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.review.loadingItems(widget.plan);
    final deck = RecordedDeck.fromLayout({
      'status': 'available',
      'layout': widget.plan['layout'],
    });
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Where to load',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        const Text(
          'Highlighted positions are needed for this experiment. Letters identify carriers; numbers inside each carrier identify sites. P1, P2… link preparation items to the cards below.',
        ),
        const SizedBox(height: 12),
        if (deck != null)
          RecordedDeckBoard(
            deck: deck,
            keys: itemKeys,
            scrollController: scroll,
            selectedEntity: selected,
            annotations: {
              for (final item in items)
                item['id']: {
                  'number': item['number'],
                  'label': item['title'],
                  'kind': item['kind'],
                },
            },
            onItem: (item) {
              if (items.any((v) => v['id'] == item['id'])) select(item['id']);
            },
          )
        else
          const Text(
            'A graphical deck is not available for this driver. Use the location instructions below.',
          ),
        const SizedBox(height: 20),
        const Text(
          'Loading checklist',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        const Text(
          'Review these declared requirements at the instrument before a hardware run. Physical loading is not detected.',
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, constraints) {
            final width = constraints.maxWidth >= 680
                ? (constraints.maxWidth - 12) / 2
                : constraints.maxWidth;
            return Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final item in items)
                  SizedBox(
                    width: width,
                    child: Card(
                      margin: EdgeInsets.zero,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(
                          color: selected == item['id']
                              ? const Color(0xff247a92)
                              : const Color(0xffcbd6e0),
                          width: selected == item['id'] ? 2 : 1,
                        ),
                      ),
                      child: InkWell(
                        key: ValueKey('loading-card:${item['id']}'),
                        borderRadius: BorderRadius.circular(12),
                        onTap: () => select(item['id'], reveal: true),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  CircleAvatar(
                                    radius: 14,
                                    child: Text(
                                      item['number'],
                                      style: const TextStyle(fontSize: 13),
                                    ),
                                  ),
                                  const SizedBox(width: 10),
                                  NativeLabwareSymbol(kind: item['kind']),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      item['title'],
                                      style: const TextStyle(
                                        fontSize: 17,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              Text(
                                item['carrier_address'],
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              if (item['placement']?['track'] != null &&
                                  item['carrier_address'] !=
                                      widget.review.location(item['placement']))
                                Text(
                                  'Physical track ${item['placement']['track']}',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Color(0xff62798c),
                                  ),
                                ),
                              if (item['supply'] != true) ...[
                                const SizedBox(height: 6),
                                Text(item['model_label']),
                                for (final vessel
                                    in item['containers'] as List? ?? [])
                                  Padding(
                                    padding: const EdgeInsets.only(top: 6),
                                    child: Text(
                                      widget.review.containerInstruction(
                                        vessel,
                                      ),
                                    ),
                                  ),
                              ] else ...[
                                const SizedBox(height: 6),
                                Text(
                                  '${(item['positions'] as List? ?? []).length} configured tip positions',
                                ),
                                Text(
                                  item['required'] == null
                                      ? 'Required quantity and remaining stock are checked before execution.'
                                      : '${item['required']} required; remaining stock is checked before execution.',
                                ),
                              ],
                              ExpansionTile(
                                tilePadding: EdgeInsets.zero,
                                title: const Text(
                                  'Model and placement details',
                                  style: TextStyle(fontSize: 12),
                                ),
                                children: [
                                  ListTile(
                                    contentPadding: EdgeInsets.zero,
                                    title: Text(
                                      'Model: ${item['model'] ?? 'Not supplied'}',
                                    ),
                                    subtitle: Text('Layout ID: ${item['id']}'),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}
